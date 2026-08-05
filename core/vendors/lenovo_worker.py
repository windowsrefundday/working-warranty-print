import concurrent.futures
import os
import queue
import threading
from dataclasses import replace
from datetime import date, datetime
from typing import Callable, Dict, List, Optional, Set, Tuple

from core.cache import WarrantyCache
from core.models import AssetRecord, SourceConfidence, VendorType
from core.vendors.browser_runtime import start_browser
from core.vendors.lenovo_parser import (
    LenovoProductResolver,
    parse_lenovo_warranty,
)

ProgressCallback = Callable[[str, int], None]


class LenovoBrowserWorker:
    """Dedicated worker that owns Playwright, one long-lived context, and a serial queue.

    The sync Playwright API is created, used, restarted, and torn down on a single
    worker thread. Requests are serialized and duplicate in-flight lookups are
    coalesced. Cache entries older than 30 days are not print-safe unless refreshed.
    """
    _STARTUP_TIMEOUT_SECONDS = 30
    _RESULT_TIMEOUT_SECONDS = 60

    def __init__(
        self,
        cache: Optional[WarrantyCache] = None,
        headless: Optional[bool] = None,
    ):
        self._cache = cache
        self._headless = (
            headless
            if headless is not None
            else os.getenv("LENOVO_WARRANTY_HEADLESS", "1").lower()
            in {"1", "true", "yes"}
        )
        self._preload_enabled = os.getenv(
            "LENOVO_WARRANTY_PRELOAD", "1"
        ).lower() in {"1", "true", "yes"}

        self._queue: queue.Queue[Optional[str]] = queue.Queue()
        self._pending: Dict[str, List[concurrent.futures.Future[AssetRecord]]] = {}
        self._progress_callbacks: Dict[str, List[ProgressCallback]] = {}
        self._in_flight: Set[str] = set()
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
        """Start the browser worker and return only after startup has settled."""
        with self._lock:
            if self._running:
                return
            if self._startup_error is not None:
                return
            self._running = True

        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=self._STARTUP_TIMEOUT_SECONDS):
            with self._lock:
                self._running = False
            self._startup_error = RuntimeError("Lenovo browser startup timed out")

    def prewarm(self) -> None:
        """Block until browser context is ready."""
        if not self._running:
            self.start()
        self._ready.wait()

    def stop(self) -> None:
        """Signal the worker and let its owning thread close Playwright."""
        with self._lock:
            self._running = False

        self._queue.put(None)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=15)

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
        """Return a cached record if fresh (<=30d), else perform live lookup."""
        serial = serial.strip().upper()
        self._emit_direct(progress_callback, "Checking verified cache", 5)
        cached = self._cache.get("Lenovo", serial) if self._cache else None
        if cached is not None and self._is_fresh(cached):
            self._emit_direct(progress_callback, "Verified cache hit", 100)
            return self._from_cache(cached)

        if not self._running:
            self.start()
        if self._startup_error is not None or not self._running:
            error = str(self._startup_error or "Lenovo browser worker is unavailable")
            self._emit_direct(progress_callback, "Lookup failed", 100)
            return self._lookup_failed(serial, error)

        return self._live_lookup(serial, progress_callback)

    def enqueue_refresh(self, serial: str) -> None:
        serial = serial.strip().upper()
        self._enqueue_refresh(serial)

    def _enqueue_refresh(self, serial: str) -> None:
        if not self._running:
            self.start()
        if self._startup_error is not None or not self._running:
            return
        with self._lock:
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

        with self._lock:
            if progress_callback is not None:
                self._progress_callbacks.setdefault(serial, []).append(progress_callback)
            if serial in self._in_flight:
                self._pending.setdefault(serial, []).append(future)
                already_in_flight = True
            else:
                self._in_flight.add(serial)
                self._pending[serial] = [future]

        if already_in_flight:
            self._notify(serial, "Joining lookup already in progress", 15)
            return self._await_result(serial, future)

        self._notify(serial, "Queued for Lenovo portal", 10)
        self._queue.put(serial)
        return self._await_result(serial, future)

    def _await_result(
        self, serial: str, future: concurrent.futures.Future[AssetRecord]
    ) -> AssetRecord:
        try:
            return future.result(timeout=self._RESULT_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            return self._lookup_failed(
                serial,
                f"Lenovo lookup timed out after {self._RESULT_TIMEOUT_SECONDS} seconds",
            )

    # ------------------------------------------------------------------
    # Worker Thread
    # ------------------------------------------------------------------
    def _run(self) -> None:
        try:
            try:
                self._init_browser()
            except Exception as exc:
                self._startup_error = exc
                with self._lock:
                    self._running = False
                self._ready.set()
                self._resolve_pending_failures(f"Lenovo browser startup failed: {exc}")
                return
            self._ready.set()

            while self._running:
                try:
                    serial = self._queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                if serial is None:
                    break
                self._process(serial)
        finally:
            self._cleanup()
            with self._lock:
                self._running = False
            self._ready.set()
            self._resolve_pending_failures("Lenovo browser worker stopped before lookup completed")

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
        assert self._context is not None
        page = self._context.new_page()
        try:
            page.goto(
                "https://pcsupport.lenovo.com/us/en/",
                wait_until="domcontentloaded",
                timeout=20000,
            )
            self._preloaded_page = page
        except Exception:
            page.close()

    def _restart_browser(self) -> None:
        self._cleanup()
        self._init_browser()

    def _process(self, serial: str) -> None:
        record: Optional[AssetRecord] = None
        try:
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

        if record is not None and record.source_confidence == SourceConfidence.VERIFIED_LIVE:
            if self._cache is not None:
                try:
                    self._cache.set(record)
                except Exception:
                    pass

        cached = (
            self._cache.get("Lenovo", serial)
            if self._cache is not None
            and (record is None or record.source_confidence != SourceConfidence.VERIFIED_LIVE)
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
            result = self._lookup_failed(
                serial,
                error=(record.lookup_error if record else None)
                or "Lenovo portal did not return a complete verified result",
            )

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
        assert self._context is not None
        if self._preloaded_page is not None:
            page = self._preloaded_page
            self._preloaded_page = None
            return page
        return self._context.new_page()

    def _scrape(self, serial: str) -> Optional[AssetRecord]:
        # Stage 1: Resolve Lenovo Product Id & Name
        self._notify(serial, "Resolving Lenovo product", 15)
        product_id, product_name, resolve_err = LenovoProductResolver.resolve_product(
            serial
        )
        if resolve_err or not product_id:
            return self._lookup_failed(
                serial, error=resolve_err or "Failed to resolve Lenovo product"
            )

        self._notify(serial, "Product verified", 25)

        # Stage 2: Read the public warranty document's structured payload.
        # Normal Playwright navigation is currently served a 403 by Lenovo's
        # edge, while this public document is returned normally. No browser
        # request interception or challenge bypass is used.
        self._notify(serial, "Loading Lenovo warranty details", 50)
        payload, fetch_error = LenovoProductResolver.fetch_warranty_payload(product_id)
        if fetch_error or payload is None:
            return self._lookup_failed(
                serial, fetch_error or "Lenovo warranty document was empty"
            )
        self._notify(serial, "Reading structured coverage details", 85)
        parsed = parse_lenovo_warranty(serial, payload, product_name)
        if parsed is None:
            return self._lookup_failed(
                serial,
                error="Lenovo returned a page without a complete matching structured warranty result",
            )
        return parsed

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
        status = LenovoBrowserWorker._calculate_status(cached.expiration_date)
        return replace(
            cached,
            warranty_status=status,
            source_confidence=SourceConfidence.CACHED_REGISTRY,
            raw_source="Lenovo Cached Warranty Registry",
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    @staticmethod
    def _calculate_status(expiration_date: str) -> str:
        for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
            try:
                exp = datetime.strptime(expiration_date, fmt).date()
                days = (exp - date.today()).days
                if days < 0:
                    return "Expired"
                if days <= 30:
                    return "Coverage Expiring"
                return "Active"
            except ValueError:
                pass
        return "Unknown"

    @staticmethod
    def _lookup_failed(serial: str, error: str = "Lenovo lookup failed") -> AssetRecord:
        return AssetRecord(
            serial_number=serial,
            vendor=VendorType.LENOVO,
            model_name="Unknown",
            warranty_status="Lookup Failed",
            ship_date="Unknown",
            expiration_date="Unknown",
            entitlements=[],
            source_confidence=SourceConfidence.UNVERIFIED_FAILED,
            raw_source="Lenovo Warranty Portal Lookup Failed",
            lookup_error=error,
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
            pass
