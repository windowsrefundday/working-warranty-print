import os
import tempfile
import threading
import time
import unittest
from datetime import date, timedelta
import typing
from typing import Any
from unittest.mock import MagicMock, patch

from core.cache import WarrantyCache
from core.models import AssetRecord, Entitlement, SourceConfidence, VendorType
from core.vendors.browser_runtime import BrowserSession
from core.vendors.hp_worker import HPBrowserWorker


class FakeBrowser:
    def __init__(self):
        self.closed = False
        self.contexts: list[FakeContext] = []

    def new_context(self, **kwargs):
        ctx = FakeContext(self)
        self.contexts.append(ctx)
        return ctx

    def close(self):
        self.closed = True
        for ctx in self.contexts:
            ctx.closed = True


class FakeContext:
    def __init__(self, browser: FakeBrowser):
        self.browser = browser
        self.closed = False
        self._page_count = 0
        self.pages_created: list[FakePage] = []

    def new_page(self):
        self._page_count += 1
        page = FakePage(self, f"page_{self._page_count}")
        self.pages_created.append(page)
        return page

    def close(self):
        self.closed = True


class FakePage:
    def __init__(self, context: FakeContext, name: str):
        self.context = context
        self.name = name
        self.closed = False

    def close(self):
        self.closed = True


class HPBrowserWorkerTests(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        self.cache = WarrantyCache(self.db_path)
        self.worker = HPBrowserWorker(cache=self.cache, headless=True)

    def tearDown(self):
        if self.worker._thread is not None and self.worker._thread.is_alive():
            self.worker.stop()
        try:
            os.remove(self.db_path)
        except FileNotFoundError:
            pass

    def _make_record(
        self,
        serial: str,
        expiration: str,
        verified_at: str,
        status: str = "Active",
    ) -> AssetRecord:
        return AssetRecord(
            serial_number=serial,
            vendor=VendorType.HP,
            model_name="HP TEST MODEL 001",
            warranty_status=status,
            ship_date="January 1, 2099",
            expiration_date=expiration,
            entitlements=[Entitlement("TEST-SUPPORT", status)],
            source_confidence=SourceConfidence.VERIFIED_LIVE,
            raw_source="Live HP Warranty Portal",
            source_verified_at=verified_at,
        )

    def _start_with_fake_browser(self):
        """Start worker with a fake browser/context so no real Chromium launches.

        Assign self.worker._scrape_page *before* calling this helper so the worker
        thread sees the fake scraper deterministically.
        """
        fake_browser = FakeBrowser()
        fake_context = fake_browser.new_context()

        def fake_init_browser():
            self.worker._playwright = MagicMock()
            self.worker._browser = fake_browser  # type: ignore[assignment]
            self.worker._context = fake_context  # type: ignore[assignment]

        import unittest.mock
        with unittest.mock.patch.object(
            self.worker, "_init_browser", side_effect=fake_init_browser
        ):
            self.worker.start()

        return fake_browser, fake_context

    def _scrape_page_results(self, results: dict[str, AssetRecord | None]):
        """Return a fake scraper that returns results[serial] and records pages."""
        used_pages: list[FakePage] = []

        def fake_scrape_page(serial, page):
            time.sleep(0.01)  # simulate tiny portal work
            used_pages.append(page)
            return results.get(serial)

        return used_pages, fake_scrape_page

    def test_two_sequential_lookups_reuse_one_context_and_separate_pages(self):
        record1 = self._make_record("MXLTEST010", "January 1, 2100", date.today().isoformat())
        record2 = self._make_record("MXLTEST011", "January 1, 2100", date.today().isoformat())
        used_pages, fake_scrape = self._scrape_page_results(
            {"MXLTEST010": record1, "MXLTEST011": record2}
        )
        self.worker._scrape_page = fake_scrape
        fake_browser, fake_context = self._start_with_fake_browser()

        result1 = self.worker.fetch_warranty("MXLTEST010")
        result2 = self.worker.fetch_warranty("MXLTEST011")

        self.assertEqual(result1.serial_number, "MXLTEST010")
        self.assertEqual(result2.serial_number, "MXLTEST011")
        self.assertEqual(len(fake_browser.contexts), 1)
        self.assertEqual(len(fake_context.pages_created), 2)
        self.assertEqual(len(used_pages), 2)
        self.assertIs(used_pages[0].context, fake_context)
        self.assertIs(used_pages[1].context, fake_context)
        self.assertNotEqual(used_pages[0].name, used_pages[1].name)
        self.assertTrue(all(p.closed for p in fake_context.pages_created))

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

    def test_startup_failure_returns_explicit_failure_without_hanging(self):
        with patch.object(
            self.worker, "_init_browser", side_effect=RuntimeError("no browser")
        ):
            with self.assertRaisesRegex(RuntimeError, "no browser"):
                self.worker.start()

        started = time.monotonic()
        result = self.worker.fetch_warranty("MXLTEST001")

        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(result.source_confidence, SourceConfidence.UNVERIFIED_FAILED)
        self.assertIn("no browser", result.lookup_error or "")
        self.assertFalse(self.worker._running)

    def test_lookup_started_during_startup_failure_resolves_without_hanging(self):
        startup_entered = threading.Event()
        release_startup = threading.Event()

        def blocked_init_browser():
            startup_entered.set()
            self.assertTrue(release_startup.wait(timeout=2))
            raise RuntimeError("no browser")

        with patch.object(self.worker, "_init_browser", side_effect=blocked_init_browser):
            start_errors: list[Exception] = []
            starter = threading.Thread(
                target=lambda: self._capture_exception(
                    self.worker.start, start_errors
                )
            )
            starter.start()
            self.assertTrue(startup_entered.wait(timeout=2))

            results: list[AssetRecord] = []
            lookup = threading.Thread(
                target=lambda: results.append(
                    self.worker.fetch_warranty("MXLTEST002")
                )
            )
            lookup.start()
            deadline = time.monotonic() + 2
            while "MXLTEST002" not in self.worker._in_flight:
                if time.monotonic() >= deadline:
                    self.fail("lookup was not registered before startup failed")
                time.sleep(0.01)

            release_startup.set()
            lookup.join(timeout=2)
            starter.join(timeout=2)

        self.assertFalse(lookup.is_alive())
        self.assertFalse(starter.is_alive())
        self.assertEqual(len(start_errors), 1)
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0].source_confidence, SourceConfidence.UNVERIFIED_FAILED
        )
        self.assertIn("no browser", results[0].lookup_error or "")

    def test_restart_waits_for_new_browser_initialization(self):
        self.worker._init_browser = lambda: None
        self.worker.start()
        self.worker.stop()

        startup_entered = threading.Event()
        release_startup = threading.Event()

        def blocked_init_browser():
            startup_entered.set()
            self.assertTrue(release_startup.wait(timeout=2))

        with patch.object(self.worker, "_init_browser", side_effect=blocked_init_browser):
            start_errors: list[Exception] = []
            starter = threading.Thread(
                target=lambda: self._capture_exception(
                    self.worker.start, start_errors
                )
            )
            starter.start()
            self.assertTrue(startup_entered.wait(timeout=2))
            self.assertTrue(starter.is_alive())
            release_startup.set()
            starter.join(timeout=2)

        self.assertFalse(starter.is_alive())
        self.assertEqual(start_errors, [])

    @staticmethod
    def _capture_exception(callback, errors: list[Exception]) -> None:
        try:
            callback()
        except Exception as exc:
            errors.append(exc)

    def test_fresh_cache_hit_returns_immediately_and_schedules_refresh(self):
        record = self._make_record("MXLTEST010", "January 1, 2100", date.today().isoformat())
        self.cache.set(record)
        refresh_record = self._make_record("MXLTEST010", "January 1, 2030", date.today().isoformat())
        calls: list[tuple[str, object]] = []

        def fake_scrape_page(serial: str, page) -> AssetRecord:
            calls.append((serial, page))
            return refresh_record

        self.worker._scrape_page = fake_scrape_page
        self._start_with_fake_browser()

        result = self.worker.fetch_warranty("MXLTEST010")

        self.assertEqual(result.source_confidence, SourceConfidence.CACHED_REGISTRY)
        self.assertEqual(result.warranty_status, "Active")
        # A live lookup was not performed synchronously.
        self.assertEqual(calls, [])
        # Give the background refresh queue a moment to be processed.
        time.sleep(0.5)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "MXLTEST010")

    def test_progress_callback_reports_cache_hit_and_live_completion(self):
        cached = self._make_record(
            "MXLTEST010", "January 1, 2100", date.today().isoformat()
        )
        self.cache.set(cached)
        self.worker._scrape_page = lambda serial, page: cached
        self._start_with_fake_browser()

        cache_events: list[tuple[str, int]] = []
        self.worker.fetch_warranty(
            "MXLTEST010",
            lambda stage, percent: cache_events.append((stage, percent)),
        )
        self.assertEqual(cache_events[0][1], 5)
        self.assertEqual(cache_events[-1], ("Verified cache hit", 100))
        deadline = time.time() + 1
        while "MXLTEST010" in self.worker._in_flight and time.time() < deadline:
            time.sleep(0.01)
        self.assertNotIn("MXLTEST010", self.worker._in_flight)

        live = self._make_record(
            "MXLTEST011", "January 1, 2100", date.today().isoformat()
        )
        self.worker._scrape_page = lambda serial, page: live
        live_events: list[tuple[str, int]] = []
        result = self.worker.fetch_warranty(
            "MXLTEST011",
            lambda stage, percent: live_events.append((stage, percent)),
        )

        self.assertEqual(result.serial_number, "MXLTEST011")
        self.assertEqual(live_events[0][1], 5)
        self.assertIn(("Loading HP warranty form", 40), live_events)
        self.assertEqual(live_events[-1], ("Warranty verified", 100))

    def test_failed_lookup_reports_failure_at_completion(self):
        self.worker._scrape_page = lambda serial, page: self.worker._lookup_failed(serial)
        self._start_with_fake_browser()
        events: list[tuple[str, int]] = []

        result = self.worker.fetch_warranty(
            "MXLTEST500", lambda stage, percent: events.append((stage, percent))
        )

        self.assertEqual(result.source_confidence, SourceConfidence.UNVERIFIED_FAILED)
        self.assertEqual(events[-1], ("Lookup failed", 100))

    def test_duplicate_serial_requests_coalesce_to_one_live_call(self):
        record = self._make_record("MXLTEST010", "January 1, 2100", date.today().isoformat())
        scrape_count = [0]

        def slow_scrape(serial, page):
            scrape_count[0] += 1
            time.sleep(0.2)
            return record

        self.worker._scrape_page = slow_scrape
        self._start_with_fake_browser()

        results: list[AssetRecord] = []
        errors: list[Exception] = []

        def fetch_one():
            try:
                results.append(self.worker.fetch_warranty("MXLTEST010"))
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=fetch_one)
        t2 = threading.Thread(target=fetch_one)
        t1.start()
        time.sleep(0.02)  # let t1 enter the queue
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(scrape_count[0], 1)
        self.assertEqual(results[0].serial_number, "MXLTEST010")
        self.assertEqual(results[1].serial_number, "MXLTEST010")

    def test_hp_requests_are_serialized(self):
        records = {
            "MXLTEST010": self._make_record("MXLTEST010", "January 1, 2100", date.today().isoformat()),
            "MXLTEST011": self._make_record("MXLTEST011", "January 1, 2100", date.today().isoformat()),
        }
        active_serials: list[str] = []
        max_concurrent = [0]

        def tracking_scrape(serial, page):
            active_serials.append(serial)
            max_concurrent[0] = max(max_concurrent[0], len(active_serials))
            time.sleep(0.05)
            active_serials.remove(serial)
            return records[serial]

        self.worker._scrape_page = tracking_scrape
        self._start_with_fake_browser()

        threads = [
            threading.Thread(target=lambda s=s: self.worker.fetch_warranty(s))
            for s in ["MXLTEST010", "MXLTEST011", "MXLTEST010", "MXLTEST011"]
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(max_concurrent[0], 1)

    def test_successful_refresh_atomically_replaces_cached_data(self):
        old_record = self._make_record("MXLTEST010", "January 1, 2100", date.today().isoformat(), status="Active")
        new_record = self._make_record("MXLTEST010", "January 1, 2030", date.today().isoformat(), status="Active")
        self.cache.set(old_record)

        self.worker._scrape_page = lambda serial, page: new_record
        self._start_with_fake_browser()

        result = self.worker.fetch_warranty("MXLTEST010")
        # The synchronous return is the old cached data.
        self.assertEqual(result.expiration_date, "January 1, 2100")
        time.sleep(0.2)

        refreshed = self.cache.get("HP", "MXLTEST010")
        self.assertIsNotNone(refreshed)
        assert refreshed is not None
        self.assertEqual(refreshed.expiration_date, "January 1, 2030")

    def test_failed_refresh_preserves_last_verified_cache_entry(self):
        record = self._make_record("MXLTEST010", "January 1, 2100", date.today().isoformat())
        self.cache.set(record)

        self.worker._scrape_page = lambda serial, page: None
        self._start_with_fake_browser()

        self.worker.fetch_warranty("MXLTEST010")
        time.sleep(0.2)

        cached = self.cache.get("HP", "MXLTEST010")
        self.assertIsNotNone(cached)
        assert cached is not None
        self.assertEqual(cached.expiration_date, "January 1, 2100")
        self.assertEqual(cached.source_verified_at, record.source_verified_at)

    def test_expired_cache_requires_live_result_and_cannot_print_after_failure(self):
        stale = self._make_record(
            "MXLTEST010",
            "January 1, 2100",
            (date.today() - timedelta(days=31)).isoformat(),
        )
        self.cache.set(stale)

        self.worker._scrape_page = lambda serial, page: None
        self._start_with_fake_browser()

        result = self.worker.fetch_warranty("MXLTEST010")

        self.assertEqual(result.source_confidence, SourceConfidence.UNVERIFIED_FAILED)
        self.assertEqual(result.warranty_status, "Lookup Failed")

    def test_browser_crash_restarts_once_and_retries_then_returns_failure(self):
        original_browser, original_context = self._start_with_fake_browser()
        record = self._make_record("MXLTEST010", "January 1, 2100", date.today().isoformat())
        init_count = [0]
        scrape_attempts = [0]

        def counting_fake_init():
            init_count[0] += 1
            self.worker._playwright = MagicMock()
            self.worker._browser = FakeBrowser()  # type: ignore[assignment]
            self.worker._context = self.worker._browser.new_context()  # type: ignore[union-attr]

        def crashing_then_successful_scrape(serial, page):
            scrape_attempts[0] += 1
            if scrape_attempts[0] == 1:
                raise Exception("Target closed: browser has been closed")
            return record

        self.worker._scrape_page = crashing_then_successful_scrape
        import unittest.mock
        with unittest.mock.patch.object(
            self.worker, "_init_browser", side_effect=counting_fake_init
        ):
            result = self.worker.fetch_warranty("MXLTEST010")

        self.assertEqual(result.source_confidence, SourceConfidence.VERIFIED_LIVE)
        self.assertEqual(scrape_attempts[0], 2)
        # _init_browser was called once during the restart triggered by the crash.
        self.assertEqual(init_count[0], 1)
        self.assertIsNot(self.worker._browser, original_browser)
        self.assertIsNot(self.worker._context, original_context)
        self.assertTrue(original_context.closed)
        self.assertTrue(original_browser.closed)

    def test_browser_crash_restarts_once_and_returns_failure_after_second_failure(self):
        original_browser, original_context = self._start_with_fake_browser()
        init_count = [0]
        scrape_attempts = [0]

        def counting_fake_init():
            init_count[0] += 1
            self.worker._playwright = MagicMock()
            self.worker._browser = FakeBrowser()  # type: ignore[assignment]
            self.worker._context = self.worker._browser.new_context()  # type: ignore[union-attr]

        def always_crash(serial, page):
            scrape_attempts[0] += 1
            raise Exception("Target closed: browser has been closed")

        self.worker._scrape_page = always_crash
        import unittest.mock
        with unittest.mock.patch.object(
            self.worker, "_init_browser", side_effect=counting_fake_init
        ):
            result = self.worker.fetch_warranty("MXLTEST010")

        self.assertEqual(result.source_confidence, SourceConfidence.UNVERIFIED_FAILED)
        self.assertEqual(scrape_attempts[0], 2)
        self.assertEqual(init_count[0], 1)
        self.assertIsNot(self.worker._browser, original_browser)
        self.assertIsNot(self.worker._context, original_context)

    def test_stop_closes_pages_context_browser_and_playwright(self):
        self.worker._scrape_page = lambda serial, page: None
        fake_browser, fake_context = self._start_with_fake_browser()
        # Keep a reference to the playwright mock created by _start_with_fake_browser.
        playwright = typing.cast(MagicMock, self.worker._playwright)

        self.worker.stop()

        self.assertTrue(fake_context.closed)
        self.assertTrue(fake_browser.closed)
        playwright.stop.assert_called_once()

    def test_init_browser_uses_shared_runtime_and_records_selection(self):
        browser = FakeBrowser()
        session = BrowserSession(MagicMock(), browser, "Microsoft Edge")

        with patch("core.vendors.hp_worker.start_browser", return_value=session):
            with patch.object(self.worker, "_preload_portal"):
                self.worker._init_browser()

        self.assertEqual(self.worker._browser_runtime, "Microsoft Edge")
        self.assertIs(self.worker._browser, browser)
        self.assertIsNotNone(self.worker._context)
        self.worker._cleanup()


if __name__ == "__main__":
    unittest.main()
