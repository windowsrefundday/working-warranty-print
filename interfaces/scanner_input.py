"""Terminal scanner input and platform feedback, independent of commands."""

import select
import subprocess
import sys
import time
from collections.abc import Callable
from typing import cast


def play_scan_beep() -> None:
    if sys.platform == "darwin":
        try:
            subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], capture_output=True)
            return
        except Exception:
            pass
    print("\a", end="", flush=True)


def read_barcode_auto_submit(prompt: str) -> str:
    print(prompt, end="", flush=True)
    if not sys.stdin.isatty():
        return input().strip()
    if sys.platform == "win32":
        return _read_windows_scanner()
    return _read_posix_scanner()


def _read_windows_scanner(
    *,
    key_available: Callable[[], bool] | None = None,
    read_key: Callable[[], str] | None = None,
    now: Callable[[], float] = time.monotonic,
    pause: Callable[[float], None] = time.sleep,
) -> str:
    """Read scanner keystrokes with Enter and idle-time auto submission."""
    available_fn = key_available
    read_fn = read_key
    if available_fn is None or read_fn is None:
        import msvcrt

        available_fn = cast(Callable[[], bool], getattr(msvcrt, "kbhit"))
        read_fn = cast(Callable[[], str], getattr(msvcrt, "getwch"))
    buffer: list[str] = []
    last_key_at: float | None = None
    while True:
        if available_fn():
            char = read_fn()
            last_key_at = now()
            if char in ("\r", "\n"):
                print()
                return "".join(buffer).strip()
            if char in ("\x03", "\x04"):
                raise KeyboardInterrupt()
            if char in ("\b", "\x7f"):
                if buffer:
                    buffer.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            # Function/navigation keys arrive as a two-character sequence.
            if char in ("\x00", "\xe0"):
                if available_fn():
                    read_fn()
                continue
            if char.isprintable():
                buffer.append(char)
                sys.stdout.write(char)
                sys.stdout.flush()
        elif (
            buffer
            and len("".join(buffer).strip()) >= 5
            and last_key_at is not None
            and now() - last_key_at >= 0.12
        ):
            print()
            return "".join(buffer).strip()
        else:
            pause(0.01)


def _read_posix_scanner() -> str:
    buffer: list[str] = []
    try:
        import termios
        import tty

        fd = sys.stdin.fileno()
        tcgetattr = cast(Callable[[int], object], getattr(termios, "tcgetattr"))
        tcsetattr = cast(Callable[[int, int, object], None], getattr(termios, "tcsetattr"))
        setcbreak = cast(Callable[[int], None], getattr(tty, "setcbreak"))
        drain_when_done = cast(int, getattr(termios, "TCSADRAIN"))
        old_settings = tcgetattr(fd)
        try:
            setcbreak(fd)
            while True:
                readable, _, _ = select.select([sys.stdin], [], [], 0.12 if buffer else None)
                if readable:
                    char = sys.stdin.read(1)
                    if char in ("\r", "\n"):
                        print()
                        return "".join(buffer).strip()
                    if ord(char) in (3, 4):
                        raise KeyboardInterrupt()
                    if ord(char) in (127, 8):
                        if buffer:
                            buffer.pop()
                            sys.stdout.write("\b \b")
                            sys.stdout.flush()
                    else:
                        buffer.append(char)
                        sys.stdout.write(char)
                        sys.stdout.flush()
                elif buffer and len("".join(buffer).strip()) >= 5:
                    print()
                    return "".join(buffer).strip()
        finally:
            tcsetattr(fd, drain_when_done, old_settings)
    except Exception:
        return input().strip()
