import os
import re
from typing import Optional

from core.cache import WarrantyCache
from core.models import AssetRecord, SourceConfidence, VendorType
from core.vendors.base import BaseVendorPlugin, ProgressCallback
from core.vendors.hp_parser import parse_portal_text
from core.vendors.hp_worker import HPBrowserWorker

class HPVendorPlugin(BaseVendorPlugin):
    def __init__(
        self,
        worker: Optional[HPBrowserWorker] = None,
        cache: Optional[WarrantyCache] = None,
    ):
        self.worker = worker
        self.cache = cache

    @property
    def vendor_type(self) -> VendorType:
        return VendorType.HP

    def fetch_warranty(
        self,
        serial_number: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> AssetRecord:
        clean_sn = serial_number.strip().upper()

        # When a worker and cache are configured, prefer them. They handle fresh
        # cache hits (immediate return + background refresh), live lookups,
        # coalescing, serialization, and crash retry.
        if self.worker is not None:
            if progress_callback is None:
                live = self.worker.fetch_warranty(clean_sn)
            else:
                live = self.worker.fetch_warranty(clean_sn, progress_callback)
            if live.source_confidence == SourceConfidence.VERIFIED_LIVE:
                if self.cache is not None:
                    self.cache.set(live)
                return live
            # A fresh worker cache hit is already a verified result. Do not
            # discard it and replace it with a failed lookup.
            if live.source_confidence == SourceConfidence.CACHED_REGISTRY:
                return live
            # A failed live lookup must never be replaced with an embedded
            # warranty record. Runtime cache hits are returned above only when
            # the worker has already verified them according to its cache policy.
            return self._failed_lookup(clean_sn, live.lookup_error)

        # Fallback direct lookup path used by tests and simple integrations.
        scraped, lookup_error = self._parse_live_hp_portal(clean_sn)
        if scraped is not None:
            return scraped

        return self._failed_lookup(clean_sn, lookup_error)

    def start(self) -> None:
        if self.worker is not None:
            self.worker.start()

    def prewarm(self) -> None:
        if self.worker is not None:
            self.worker.prewarm()

    def stop(self) -> None:
        if self.worker is not None:
            self.worker.stop()

    def _failed_lookup(
        self,
        clean_sn: str,
        lookup_error: Optional[str] = None,
    ) -> AssetRecord:
        error = lookup_error or "HP did not return a complete warranty result"
        return AssetRecord(
            serial_number=clean_sn,
            vendor=VendorType.HP,
            model_name="Unknown",
            warranty_status="Lookup Failed",
            ship_date="Unknown",
            expiration_date="Unknown",
            entitlements=[],
            source_confidence=SourceConfidence.UNVERIFIED_FAILED,
            raw_source="HP Warranty Portal Lookup Failed",
            lookup_error=error,
        )

    def _parse_live_hp_portal(
        self, clean_sn: str
    ) -> tuple[AssetRecord | None, Optional[str]]:
        """Submit HP's warranty form and return its record and request-local error.

        Kept for backward compatibility with callers/tests that do not inject a
        worker. A configured worker performs the same live lookup with caching,
        serialization, and reuse of a single long-lived context.
        """
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                headless = os.getenv("HP_WARRANTY_HEADLESS", "1").lower() in {
                    "1", "true", "yes"
                }
                browser = p.chromium.launch(
                    headless=headless,
                    args=["--disable-blink-features=AutomationControlled"]
                )
                try:
                    context = browser.new_context(
                        locale="en-US",
                        user_agent=(
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/126.0.0.0 Safari/537.36"
                        ),
                    )
                    page = context.new_page()
                    page.goto(
                        "https://support.hp.com/us-en/check-warranty",
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                    serial_input = page.get_by_role(
                        "textbox", name=re.compile(r"Serial number", re.IGNORECASE)
                    )
                    serial_input.wait_for(state="visible", timeout=20000)
                    serial_input.fill(clean_sn)
                    page.get_by_role(
                        "button", name=re.compile(r"^Submit$", re.IGNORECASE)
                    ).click(timeout=15000)
                    page.wait_for_url("**/warrantyresult/**", timeout=30000)
                    page.get_by_text("Coverage details", exact=True).wait_for(
                        state="visible", timeout=20000
                    )
                    text = page.inner_text("body")
                    record = parse_portal_text(clean_sn, text)
                    if record is None:
                        return (
                            None,
                            "HP returned a page without a complete matching warranty result",
                        )
                    return record, None
                finally:
                    browser.close()
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _parse_portal_text(clean_sn: str, text: str) -> AssetRecord | None:
        """Backwards-compatible wrapper around the shared parser."""
        return parse_portal_text(clean_sn, text)
