import os
import tempfile
import time
import threading
import unittest
import typing
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from core.cache import WarrantyCache
from core.models import AssetRecord, Entitlement, SourceConfidence, VendorType
from core.vendors.browser_runtime import BrowserSession
from core.vendors.lenovo_worker import LenovoBrowserWorker


class FakeBrowser:
    def __init__(self):
        self.closed = False
        self.closed_on_thread = None
        self.contexts: list[FakeContext] = []

    def new_context(self, **kwargs):
        ctx = FakeContext(self)
        self.contexts.append(ctx)
        return ctx

    def close(self):
        self.closed = True
        self.closed_on_thread = threading.get_ident()
        for ctx in self.contexts:
            ctx.closed = True


class FakeContext:
    def __init__(self, browser: FakeBrowser):
        self.browser = browser
        self.closed = False
        self.closed_on_thread = None
        self._page_count = 0
        self.pages_created: list[FakePage] = []

    def new_page(self):
        self._page_count += 1
        page = FakePage(self, f"page_{self._page_count}")
        self.pages_created.append(page)
        return page

    def close(self):
        self.closed = True
        self.closed_on_thread = threading.get_ident()


class FakePage:
    def __init__(self, context: FakeContext, name: str):
        self.context = context
        self.name = name
        self.closed = False

    def close(self):
        self.closed = True

    def route(self, pattern, handler):
        pass

    def goto(self, url, **kwargs):
        pass

    def evaluate(self, expr, **kwargs):
        return None

    def inner_text(self, selector):
        return ""


class LenovoBrowserWorkerTests(unittest.TestCase):

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        self.cache = WarrantyCache(self.db_path)
        self.worker = LenovoBrowserWorker(cache=self.cache, headless=True)

    def tearDown(self):
        if self.worker._thread is not None and self.worker._thread.is_alive():
            self.worker.stop()
        try:
            os.remove(self.db_path)
        except FileNotFoundError:
            pass

    def _sample_record(self, serial="MZTEST001", days_ago=0):
        verified_date = (date.today() - timedelta(days=days_ago)).isoformat()
        return AssetRecord(
            serial_number=serial,
            vendor=VendorType.LENOVO,
            model_name="LENOVO TEST MODEL 001",
            warranty_status="Active",
            ship_date="2099-01-01",
            expiration_date="2100-01-01",
            entitlements=[Entitlement(service_name="TEST-ONSITE-SUPPORT", status="Active")],
            source_confidence=SourceConfidence.VERIFIED_LIVE,
            raw_source="Live Lenovo Warranty Portal",
            source_verified_at=verified_date,
        )

    def _start_with_fake_browser(self):
        fake_browser = FakeBrowser()
        fake_context = fake_browser.new_context()

        def fake_init_browser():
            self.worker._playwright = MagicMock()
            self.worker._browser = fake_browser  # type: ignore[assignment]
            self.worker._context = fake_context  # type: ignore[assignment]

        with patch.object(self.worker, "_init_browser", side_effect=fake_init_browser):
            self.worker.start()

        return fake_browser, fake_context

    def test_first_lookup_starts_worker_safely(self):
        self.worker._scrape = lambda serial: self._sample_record(serial)
        self._start_with_fake_browser()

        res = self.worker.fetch_warranty("MZTEST001")
        self.assertEqual(res.serial_number, "MZTEST001")
        self.assertEqual(res.source_confidence, SourceConfidence.VERIFIED_LIVE)

    def test_first_lookup_consumes_existing_preloaded_page(self):
        fake_browser = FakeBrowser()
        fake_context = fake_browser.new_context()
        preloaded = fake_context.new_page()
        self.worker._context = fake_context  # type: ignore[assignment]
        self.worker._preloaded_page = preloaded  # type: ignore[assignment]

        first = self.worker._create_page()
        second = self.worker._create_page()

        self.assertIs(first, preloaded)
        self.assertIsNot(second, preloaded)
        self.assertIsNone(self.worker._preloaded_page)

    def test_two_sequential_lookups_reuse_one_context_and_separate_pages(self):
        fake_browser = FakeBrowser()
        fake_context = fake_browser.new_context()
        self.worker._context = fake_context  # type: ignore[assignment]

        p1 = self.worker._create_page()
        p2 = self.worker._create_page()

        self.assertEqual(len(fake_context.pages_created), 2)
        self.assertIsNot(p1, p2)
        self.assertIs(p1.context, fake_context)
        self.assertIs(p2.context, fake_context)

    def test_fresh_cache_returns_immediately_without_starting_a_refresh(self):
        rec = self._sample_record("MZTEST001", days_ago=2)
        self.cache.set(rec)

        with patch.object(self.worker, "_enqueue_refresh") as mock_refresh:
            res = self.worker.fetch_warranty("MZTEST001")
            self.assertEqual(res.serial_number, "MZTEST001")
            self.assertEqual(res.source_confidence, SourceConfidence.CACHED_REGISTRY)
            mock_refresh.assert_not_called()

    def test_cold_cache_hit_does_not_start_chromium(self):
        self.cache.set(self._sample_record("MZTEST001", days_ago=2))
        with patch.object(self.worker, "start") as start:
            result = self.worker.fetch_warranty("MZTEST001")

        self.assertEqual(result.source_confidence, SourceConfidence.CACHED_REGISTRY)
        start.assert_not_called()

    def test_startup_failure_returns_explicit_failure_without_hanging(self):
        with patch.object(self.worker, "_init_browser", side_effect=RuntimeError("no browser")):
            started = time.monotonic()
            result = self.worker.fetch_warranty("MZTEST001")
            later_result = self.worker.fetch_warranty("MZTEST002")

        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(result.source_confidence, SourceConfidence.UNVERIFIED_FAILED)
        self.assertIn("no browser", result.lookup_error or "")
        self.assertEqual(later_result.source_confidence, SourceConfidence.UNVERIFIED_FAILED)
        self.assertIn("no browser", later_result.lookup_error or "")
        self.assertFalse(self.worker._running)

    def test_duplicate_serial_requests_coalesce_to_one_live_call(self):
        call_count = [0]

        def slow_scrape(serial):
            call_count[0] += 1
            time.sleep(0.1)
            return self._sample_record(serial)

        self.worker._scrape = slow_scrape
        self._start_with_fake_browser()

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            f1 = executor.submit(self.worker.fetch_warranty, "MZTEST001")
            f2 = executor.submit(self.worker.fetch_warranty, "MZTEST001")
            f3 = executor.submit(self.worker.fetch_warranty, "MZTEST001")

            r1 = f1.result()
            r2 = f2.result()
            r3 = f3.result()

        self.assertEqual(call_count[0], 1)
        self.assertEqual(r1.serial_number, "MZTEST001")
        self.assertEqual(r2.serial_number, "MZTEST001")
        self.assertEqual(r3.serial_number, "MZTEST001")

    def test_lenovo_requests_are_serialized(self):
        active_serials: list[str] = []
        max_concurrent = [0]

        def tracking_scrape(serial):
            active_serials.append(serial)
            max_concurrent[0] = max(max_concurrent[0], len(active_serials))
            time.sleep(0.05)
            active_serials.remove(serial)
            return self._sample_record(serial)

        self.worker._scrape = tracking_scrape
        self._start_with_fake_browser()

        import threading
        threads = [
            threading.Thread(target=lambda s=s: self.worker.fetch_warranty(s))
            for s in ["MZTEST010", "MZTEST011", "MZTEST010", "MZTEST011"]
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(max_concurrent[0], 1)

    def test_failed_refresh_preserves_last_verified_cache_entry(self):
        old_rec = self._sample_record("MZTEST001", days_ago=5)
        self.cache.set(old_rec)
        self.worker._scrape = lambda serial: None
        self._start_with_fake_browser()

        self.worker.fetch_warranty("MZTEST001")
        time.sleep(0.2)

        in_cache = self.cache.get("Lenovo", "MZTEST001")
        self.assertIsNotNone(in_cache)
        assert in_cache is not None
        self.assertEqual(in_cache.source_confidence, SourceConfidence.VERIFIED_LIVE)
        self.assertEqual(in_cache.expiration_date, "2100-01-01")

    def test_stale_cache_plus_live_failure_returns_unverified_failed(self):
        stale_rec = self._sample_record("MZTEST001", days_ago=35)
        self.cache.set(stale_rec)
        self.worker._scrape = lambda serial: None
        self._start_with_fake_browser()

        res = self.worker.fetch_warranty("MZTEST001")
        self.assertEqual(res.source_confidence, SourceConfidence.UNVERIFIED_FAILED)

    def test_browser_crash_restarts_once_and_retries(self):
        original_browser, original_context = self._start_with_fake_browser()
        init_count = [0]
        scrape_attempts = [0]

        def counting_fake_init():
            init_count[0] += 1
            self.worker._playwright = MagicMock()
            self.worker._browser = FakeBrowser()  # type: ignore[assignment]
            self.worker._context = self.worker._browser.new_context()  # type: ignore[union-attr]

        def crashing_then_successful_scrape(serial):
            scrape_attempts[0] += 1
            if scrape_attempts[0] == 1:
                raise Exception("Target closed: browser has been closed")
            return self._sample_record(serial)

        self.worker._scrape = crashing_then_successful_scrape
        with patch.object(self.worker, "_init_browser", side_effect=counting_fake_init):
            res = self.worker.fetch_warranty("MZTEST001")

        self.assertEqual(res.source_confidence, SourceConfidence.VERIFIED_LIVE)
        self.assertEqual(scrape_attempts[0], 2)
        self.assertEqual(init_count[0], 1)
        self.assertTrue(original_context.closed)
        self.assertTrue(original_browser.closed)

    def test_second_crash_returns_failure(self):
        self._start_with_fake_browser()
        init_count = [0]
        scrape_attempts = [0]

        def counting_fake_init():
            init_count[0] += 1
            self.worker._playwright = MagicMock()
            self.worker._browser = FakeBrowser()  # type: ignore[assignment]
            self.worker._context = self.worker._browser.new_context()  # type: ignore[union-attr]

        def always_crash(serial):
            scrape_attempts[0] += 1
            raise Exception("Target closed: browser has been closed")

        self.worker._scrape = always_crash
        with patch.object(self.worker, "_init_browser", side_effect=counting_fake_init):
            res = self.worker.fetch_warranty("MZTEST001")

        self.assertEqual(res.source_confidence, SourceConfidence.UNVERIFIED_FAILED)
        self.assertEqual(scrape_attempts[0], 2)
        self.assertEqual(init_count[0], 1)

    def test_stop_closes_pages_context_browser_and_playwright(self):
        self.worker._scrape = lambda serial: None
        fake_browser, fake_context = self._start_with_fake_browser()
        playwright = typing.cast(MagicMock, self.worker._playwright)

        self.worker.stop()

        self.assertTrue(fake_context.closed)
        self.assertTrue(fake_browser.closed)
        playwright.stop.assert_called_once()

    def test_stop_closes_browser_resources_on_worker_thread(self):
        self.worker._scrape = lambda serial: None
        fake_browser, fake_context = self._start_with_fake_browser()
        self.assertIsNotNone(self.worker._thread)
        assert self.worker._thread is not None
        worker_thread_id = self.worker._thread.ident

        self.worker.stop()

        self.assertTrue(fake_context.closed)
        self.assertTrue(fake_browser.closed)
        self.assertEqual(fake_context.closed_on_thread, worker_thread_id)
        self.assertEqual(fake_browser.closed_on_thread, worker_thread_id)

    def test_init_browser_uses_shared_runtime_and_records_selection(self):
        browser = FakeBrowser()
        session = BrowserSession(MagicMock(), browser, "Google Chrome")

        with patch("core.vendors.lenovo_worker.start_browser", return_value=session):
            with patch.object(self.worker, "_preload_portal"):
                self.worker._init_browser()

        self.assertEqual(self.worker._browser_runtime, "Google Chrome")
        self.assertIs(self.worker._browser, browser)
        self.assertIsNotNone(self.worker._context)
        self.worker._cleanup()

    def test_failed_lookup_reports_failure_at_completion(self):
        self.worker._scrape = lambda serial: self.worker._lookup_failed(serial, "portal down")
        self._start_with_fake_browser()
        stages = []

        result = self.worker.fetch_warranty("MZTEST001", progress_callback=lambda stage, pct: stages.append((stage, pct)))

        self.assertEqual(result.source_confidence, SourceConfidence.UNVERIFIED_FAILED)
        self.assertEqual(stages[-1], ("Lookup failed", 100))

    def test_progress_callback_reports_cache_hit_and_live_completion(self):
        self.worker._scrape = lambda serial: self._sample_record(serial)
        self._start_with_fake_browser()

        stages = []
        def cb(stage, pct):
            stages.append((stage, pct))

        self.worker.fetch_warranty("MZTEST001", progress_callback=cb)
        self.assertGreater(len(stages), 0)
        self.assertEqual(stages[0][0], "Checking verified cache")
        self.assertEqual(stages[-1][1], 100)


if __name__ == "__main__":
    unittest.main()
