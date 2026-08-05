import concurrent.futures
import os
import queue
import re
import threading
import time
from dataclasses import replace
from datetime import date, datetime
from typing import Callable, List, Optional

from core.cache import WarrantyCache
from core.models import AssetRecord, SourceConfidence, VendorType
from core.vendors.browser_runtime import start_browser
from core.vendors.hp_parser import parse_portal_text

ProgressCallback = Callable[[str, int], None]


class HPBrowserWorker:
    """Dedicated worker that owns Playwright, one context, and a serial queue.

    The sync Playwright API is created, used, and torn down on a single worker
    thread. All live HP portal requests are serialized; duplicate in-flight
    requests for the same serial are coalesced so only one portal call is made.
    A fresh cache entry is returned immediately and a background refresh is
    enqueued. If Chromium crashes during a live lookup, the browser/session is
    restarted once and the active lookup is retried once.
    """

    def __init__(
        self,
        cache: Optional[WarrantyCache] = None,
        headless: Optional[bool] = None,
    ):
        self._cache = cache
        self._headless = (
            headless
            if headless is not None
            else os.getenv("HP_WARRANTY_HEADLESS", "1").lower()
            in {"1", "true", "yes"}
        )
        self._preload_enabled = os.getenv("HP_WARRANTY_PRELOAD", "1").lower() in {
            "1",
            "true",
            "yes",
        }
        self._queue: queue.Queue[Optional[str]] = queue.Queue()
        self._pending: dict[str, List[concurrent.futures.Future[AssetRecord]]] = {}
        self._progress_callbacks: dict[str, List[ProgressCallback]] = {}
        self._in_flight: set[str] = set()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._ready = threading.Event()
        self._playwright = None
        self._browser = None
        self._browser_runtime: Optional[str] = None
        self._context = None
        self._preloaded_page = None
        self._startup_error: Optional[Exception] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start the worker thread and initialize the browser."""
        with self._lock:
            self._running = True
            self._startup_error = None
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait()
        with self._lock:
            startup_error = self._startup_error
        if startup_error is not None:
            raise startup_error

    def prewarm(self) -> None:
        """Block until the browser context is ready for the first lookup."""
        self._ready.wait()

    def stop(self) -> None:
        """Signal the worker to stop and close all browser resources."""
        with self._lock:
            self._running = False
        self._queue.put(None)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=15)
        self._cleanup()

    def _cleanup(self) -> None:
        self._preloaded_page = None
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        self._browser_runtime = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def fetch_warranty(
        self,
        serial: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> AssetRecord:
        """Return a cached record immediately if fresh, else wait for live lookup."""
        serial = serial.strip().upper()
        self._emit_direct(progress_callback, "Checking verified cache", 5)
        cached = self._cache.get("HP", serial) if self._cache else None
        if cached is not None and self._is_fresh(cached):
            self._emit_direct(progress_callback, "Verified cache hit", 100)
            self._enqueue_refresh(serial)
            return self._from_cache(cached)
        return self._live_lookup(serial, progress_callback)

    def enqueue_refresh(self, serial: str) -> None:
        """Enqueue a background refresh for an already-fresh cached serial."""
        serial = serial.strip().upper()
        self._enqueue_refresh(serial)

    def _enqueue_refresh(self, serial: str) -> None:
        with self._lock:
            if self._startup_error is not None or not self._running:
                return
            if serial in self._in_flight:
                return
            self._in_flight.add(serial)
            self._queue.put(serial)

    def _live_lookup(
        self,
        serial: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> AssetRecord:
        future: concurrent.futures.Future[AssetRecord] = concurrent.futures.Future()
        already_in_flight = False
        unavailable_error: Optional[str] = None
        with self._lock:
            if self._startup_error is not None or not self._running:
                unavailable_error = str(
                    self._startup_error or "HP browser worker is unavailable"
                )
            else:
                if progress_callback is not None:
                    self._progress_callbacks.setdefault(serial, []).append(
                        progress_callback
                    )
                if serial in self._in_flight:
                    self._pending.setdefault(serial, []).append(future)
                    already_in_flight = True
                else:
                    self._in_flight.add(serial)
                    self._pending[serial] = [future]
                    # Keep registration and enqueueing under the same lock as
                    # the availability check. A concurrent startup failure or
                    # stop can then either resolve this future or observe that
                    # no work should be queued.
                    self._queue.put(serial)
        if unavailable_error is not None:
            self._emit_direct(progress_callback, "Lookup failed", 100)
            return self._lookup_failed(serial, unavailable_error)
        if already_in_flight:
            self._notify(serial, "Joining lookup already in progress", 15)
            return future.result()
        self._notify(serial, "Queued for HP portal", 10)
        return future.result()

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------
    def _run(self) -> None:
        try:
            self._init_browser()
        except Exception as exc:
            with self._lock:
                self._startup_error = exc
                self._running = False
            self._resolve_pending_failures(f"HP browser startup failed: {exc}")
            self._ready.set()
            return
        self._ready.set()

        while self._is_running():
            try:
                serial = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if serial is None:
                break
            self._process(serial)

    def _is_running(self) -> bool:
        with self._lock:
            return self._running

    def _resolve_pending_failures(self, error: str) -> None:
        with self._lock:
            pending = self._pending
            callbacks = self._progress_callbacks
            self._pending = {}
            self._progress_callbacks = {}
            self._in_flight.clear()
        for serial, futures in pending.items():
            result = self._lookup_failed(serial, error)
            for callback in callbacks.get(serial, []):
                self._emit_direct(callback, "Lookup failed", 100)
            for future in futures:
                if not future.done():
                    future.set_result(result)

    def _init_browser(self) -> None:
        session = start_browser(
            headless=self._headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._playwright = session.playwright
        self._browser = session.browser
        self._browser_runtime = session.runtime
        try:
            self._context = self._browser.new_context(
                locale="en-US",
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
            )
            if self._preload_enabled:
                self._preload_portal()
        except Exception:
            self._cleanup()
            raise

    def _preload_portal(self) -> None:
        """Keep one unused HP form ready for the first live lookup."""
        assert self._context is not None
        page = self._context.new_page()
        try:
            page.goto(
                "https://support.hp.com/us-en/check-warranty",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            page.get_by_role(
                "textbox", name=re.compile(r"Serial number", re.IGNORECASE)
            ).wait_for(state="visible", timeout=20000)
            self._preloaded_page = page
        except Exception:
            # Preloading is an optimization. A transient preload failure must
            # not prevent the normal lookup path from trying later.
            page.close()

    def _restart_browser(self) -> None:
        self._cleanup()
        self._init_browser()

    def _process(self, serial: str) -> None:
        record: Optional[AssetRecord] = None
        try:
            self._notify(serial, "Opening preloaded HP session", 25)
            record = self._scrape(serial)
        except Exception as exc:
            if self._is_crash(exc):
                self._notify(serial, "Restarting browser session", 30)
                self._restart_browser()
                try:
                    record = self._scrape(serial)
                except Exception:
                    record = None
            else:
                record = None

        if record is not None and self._cache is not None:
            try:
                self._cache.set(record)
            except Exception:
                # A cache write failure must not crash the worker or affect the
                # returned live result.
                pass

        cached = (
            self._cache.get("HP", serial)
            if self._cache is not None and record is None
            else None
        )
        with self._lock:
            futures = self._pending.pop(serial, [])
            self._in_flight.discard(serial)
            callbacks = self._progress_callbacks.pop(serial, [])
        if record is not None and record.source_confidence == SourceConfidence.VERIFIED_LIVE:
            result = record
        elif cached is not None and self._is_fresh(cached):
            result = self._from_cache(cached)
        else:
            result = self._lookup_failed(serial)
        if result.source_confidence == SourceConfidence.VERIFIED_LIVE:
            final_stage = "Warranty verified"
        elif result.source_confidence == SourceConfidence.CACHED_REGISTRY:
            final_stage = "Verified cache hit"
        else:
            final_stage = "Lookup failed"
        for callback in callbacks:
            self._emit_direct(callback, final_stage, 100)
        for fut in futures:
            if not fut.done():
                fut.set_result(result)

    def _create_page(self):
        """Consume the unused preloaded form, then create fresh pages."""
        assert self._context is not None
        if self._preloaded_page is not None:
            page = self._preloaded_page
            self._preloaded_page = None
            return page
        return self._context.new_page()

    def _scrape(self, serial: str) -> Optional[AssetRecord]:
        """Submit HP's supported warranty form and parse its result page.

        A fresh page is created and closed for every lookup while the same
        long-lived browser context is reused.
        """
        page = self._create_page()
        try:
            if "/check-warranty" in str(getattr(page, "url", "")):
                self._notify(serial, "Using preloaded HP form", 40)
            else:
                self._notify(serial, "Loading HP warranty form", 40)
            return self._scrape_page(serial, page)
        finally:
            page.close()

    def _scrape_page(self, serial: str, page) -> Optional[AssetRecord]:
        """Perform the actual HP portal navigation and parse the result."""
        if "/check-warranty" not in str(getattr(page, "url", "")):
            page.goto(
                "https://support.hp.com/us-en/check-warranty",
                wait_until="domcontentloaded",
                timeout=30000,
            )
        serial_input = page.get_by_role(
            "textbox", name=re.compile(r"Serial number", re.IGNORECASE)
        )
        serial_input.wait_for(state="visible", timeout=20000)
        self._notify(serial, "Submitting serial number", 60)
        serial_input.fill(serial)
        page.get_by_role(
            "button", name=re.compile(r"^Submit$", re.IGNORECASE)
        ).click(timeout=15000)
        page.wait_for_url("**/warrantyresult/**", timeout=30000)
        page.get_by_text("Coverage details", exact=True).wait_for(
            state="visible", timeout=20000
        )
        self._notify(serial, "Reading coverage details", 85)
        text = page.inner_text("body")
        return parse_portal_text(serial, text)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _is_fresh(record: AssetRecord) -> bool:
        if not record.source_verified_at:
            return False
        try:
            verified = datetime.strptime(
                record.source_verified_at, "%Y-%m-%d"
            ).date()
        except ValueError:
            return False
        return (date.today() - verified).days <= 30

    @staticmethod
    def _from_cache(cached: AssetRecord) -> AssetRecord:
        status = HPBrowserWorker._calculate_status(cached.expiration_date)
        return replace(
            cached,
            warranty_status=status,
            source_confidence=SourceConfidence.CACHED_REGISTRY,
            raw_source="HP Cached Warranty Registry",
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    @staticmethod
    def _calculate_status(expiration_date: str) -> str:
        try:
            exp = datetime.strptime(expiration_date, "%B %d, %Y").date()
        except ValueError:
            return "Unknown"
        days = (exp - date.today()).days
        if days < 0:
            return "Expired"
        if days <= 30:
            return "Coverage Expiring"
        return "Active"

    @staticmethod
    def _lookup_failed(serial: str, error: Optional[str] = None) -> AssetRecord:
        return AssetRecord(
            serial_number=serial,
            vendor=VendorType.HP,
            model_name="Unknown",
            warranty_status="Lookup Failed",
            ship_date="Unknown",
            expiration_date="Unknown",
            entitlements=[],
            source_confidence=SourceConfidence.UNVERIFIED_FAILED,
            raw_source="HP Warranty Portal Lookup Failed",
            lookup_error=error or "HP did not return a complete warranty result",
        )

    @staticmethod
    def _is_crash(exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(
            token in msg
            for token in (
                "target closed",
                "browser has been closed",
                "connection closed",
                "crashed",
                "chromium",
            )
        )

    def _notify(self, serial: str, stage: str, percent: int) -> None:
        with self._lock:
            callbacks = list(self._progress_callbacks.get(serial, []))
        for callback in callbacks:
            self._emit_direct(callback, stage, percent)

    @staticmethod
    def _emit_direct(
        callback: Optional[ProgressCallback],
        stage: str,
        percent: int,
    ) -> None:
        if callback is None:
            return
        try:
            callback(stage, percent)
        except Exception:
            # Display callbacks must never be allowed to break a lookup.
            pass
