"""Shared Playwright browser discovery and launch behavior."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence


BrowserStart = Callable[[], Any]


@dataclass(frozen=True)
class BrowserSession:
    """A started Playwright runtime and the browser it launched."""

    playwright: Any
    browser: Any
    runtime: str


class BrowserLaunchError(RuntimeError):
    """Raised when every permitted browser runtime fails to launch."""

    def __init__(self, attempts: Sequence[tuple[str, Exception]]):
        self.attempts = tuple(attempts)
        detail = "; ".join(f"{name}: {error}" for name, error in self.attempts)
        super().__init__(f"No supported browser runtime could be launched ({detail})")


def _start_playwright() -> Any:
    from playwright.sync_api import sync_playwright

    return sync_playwright().start()


def launch_browser(
    playwright: Any,
    *,
    headless: bool,
    args: Sequence[str],
    platform_name: Optional[str] = None,
) -> tuple[Any, str]:
    """Try the bundled browser, then Windows system browsers."""
    actual_platform = platform_name or sys.platform
    attempts: list[tuple[str, Exception]] = []
    candidates: list[tuple[str, dict[str, Any]]] = [
        ("bundled Chromium", {"headless": headless, "args": list(args)}),
    ]
    if actual_platform == "win32":
        candidates.extend(
            [
                (
                    "Microsoft Edge",
                    {"channel": "msedge", "headless": headless, "args": list(args)},
                ),
                (
                    "Google Chrome",
                    {"channel": "chrome", "headless": headless, "args": list(args)},
                ),
            ]
        )

    for runtime, options in candidates:
        try:
            return playwright.chromium.launch(**options), runtime
        except Exception as exc:
            attempts.append((runtime, exc))
    raise BrowserLaunchError(attempts)


def start_browser(
    *,
    headless: bool,
    args: Sequence[str],
    platform_name: Optional[str] = None,
    playwright_start: Optional[BrowserStart] = None,
) -> BrowserSession:
    """Start Playwright and launch a permitted browser runtime safely."""
    playwright = (playwright_start or _start_playwright)()
    try:
        browser, runtime = launch_browser(
            playwright,
            headless=headless,
            args=args,
            platform_name=platform_name,
        )
        return BrowserSession(playwright, browser, runtime)
    except Exception:
        try:
            playwright.stop()
        except Exception:
            pass
        raise


def available_system_browsers(
    *,
    platform_name: Optional[str] = None,
    environment: Optional[Mapping[str, str]] = None,
) -> tuple[str, ...]:
    """Return Windows system browsers that Playwright can reasonably target."""
    if (platform_name or sys.platform) != "win32":
        return ()
    env = environment if environment is not None else os.environ
    browsers: list[str] = []
    for channel, relative_path in (
        ("msedge", Path("Microsoft") / "Edge" / "Application" / "msedge.exe"),
        ("chrome", Path("Google") / "Chrome" / "Application" / "chrome.exe"),
    ):
        if shutil.which(channel, path=env.get("PATH")):
            browsers.append(channel)
            continue
        roots = [
            env.get("PROGRAMFILES"),
            env.get("PROGRAMFILES(X86)"),
            env.get("LOCALAPPDATA"),
        ]
        if any(root and (Path(root) / relative_path).is_file() for root in roots):
            browsers.append(channel)
    return tuple(browsers)
