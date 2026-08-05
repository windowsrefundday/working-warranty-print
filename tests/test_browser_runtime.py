import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.vendors.browser_runtime import (
    BrowserLaunchError,
    available_system_browsers,
    launch_browser,
    start_browser,
)


class BrowserRuntimeTests(unittest.TestCase):
    def test_bundled_chromium_is_preferred(self):
        playwright = MagicMock()
        bundled = object()
        playwright.chromium.launch.return_value = bundled

        browser, runtime = launch_browser(
            playwright,
            headless=True,
            args=["--test"],
            platform_name="win32",
        )

        self.assertIs(browser, bundled)
        self.assertEqual(runtime, "bundled Chromium")
        playwright.chromium.launch.assert_called_once_with(
            headless=True,
            args=["--test"],
        )

    def test_edge_is_used_when_bundled_chromium_fails(self):
        playwright = MagicMock()
        edge = object()

        def launch(**options):
            if options.get("channel") == "msedge":
                return edge
            raise RuntimeError("bundled browser unavailable")

        playwright.chromium.launch.side_effect = launch

        browser, runtime = launch_browser(
            playwright,
            headless=True,
            args=[],
            platform_name="win32",
        )

        self.assertIs(browser, edge)
        self.assertEqual(runtime, "Microsoft Edge")
        self.assertEqual(playwright.chromium.launch.call_count, 2)
        self.assertEqual(
            playwright.chromium.launch.call_args_list[1].kwargs["channel"],
            "msedge",
        )

    def test_chrome_is_used_after_edge_fails(self):
        playwright = MagicMock()
        chrome = object()

        def launch(**options):
            if options.get("channel") == "chrome":
                return chrome
            raise RuntimeError(f"{options.get('channel', 'bundled')} unavailable")

        playwright.chromium.launch.side_effect = launch

        browser, runtime = launch_browser(
            playwright,
            headless=False,
            args=[],
            platform_name="win32",
        )

        self.assertIs(browser, chrome)
        self.assertEqual(runtime, "Google Chrome")
        self.assertEqual(playwright.chromium.launch.call_count, 3)

    def test_non_windows_does_not_try_system_browsers(self):
        playwright = MagicMock()
        playwright.chromium.launch.side_effect = RuntimeError("missing Chromium")

        with self.assertRaises(BrowserLaunchError) as context:
            launch_browser(
                playwright,
                headless=True,
                args=[],
                platform_name="darwin",
            )

        self.assertEqual(len(context.exception.attempts), 1)
        self.assertEqual(playwright.chromium.launch.call_count, 1)

    def test_all_failures_are_reported_and_playwright_is_stopped(self):
        playwright = MagicMock()
        playwright.chromium.launch.side_effect = RuntimeError("not installed")

        with patch(
            "core.vendors.browser_runtime._start_playwright",
            return_value=playwright,
        ):
            with self.assertRaises(BrowserLaunchError) as context:
                start_browser(headless=True, args=[], platform_name="win32")

        self.assertEqual(len(context.exception.attempts), 3)
        playwright.stop.assert_called_once()

    def test_system_browser_discovery_uses_standard_windows_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            edge = root / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            edge.parent.mkdir(parents=True)
            edge.write_text("fake", encoding="utf-8")

            browsers = available_system_browsers(
                platform_name="win32",
                environment={"PROGRAMFILES": directory, "PATH": ""},
            )

        self.assertEqual(browsers, ("msedge",))


if __name__ == "__main__":
    unittest.main()
