"""Self-healing source-checkout updater.

This module must import only the standard library. It runs before any
application module is imported, so a broken application commit can never stop
the updater from pulling the next fix or rolling back.

Update contract:

1. Fetch ``origin/main`` and fast-forward only; never merge or discard work.
2. If the requirements files changed, install them into the running
   interpreter's environment. Dependency changes are applied only at process
   start, never from the background thread while the application is running.
3. Run ``main.py --self-test`` against the new checkout. If dependency
   installation or the self-test fails, move the checkout back to the previous
   commit (``git reset --keep``), restore the previous requirements, and
   remember a self-test failure so the same commit is not retried.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, Sequence

UPDATE_INTERVAL_SECONDS = 6 * 60 * 60
DISABLE_ENV = "WARRANTY_LABEL_DISABLE_AUTO_UPDATE"
REQUIREMENT_FILES = ("requirements.txt", "requirements-windows.txt")
STATE_FILENAME = "warranty-updater.json"
LOCK_FILENAME = "warranty-updater.lock"
STALE_LOCK_SECONDS = 60 * 60
MAX_BAD_COMMITS = 50

Runner = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class UpdateResult:
    """Outcome of one update attempt."""

    status: str  # current | updated | refused | rolled_back | skipped
    detail: str = ""

    @property
    def changed(self) -> bool:
        return self.status == "updated"


class Updater:
    """Fast-forward updater with dependency sync, self-test, and rollback."""

    def __init__(
        self,
        repo_root: str,
        *,
        python_executable: str = sys.executable,
        git_executable: str | None = None,
        run: Runner = subprocess.run,
        platform: str = sys.platform,
        log: Callable[[str], None] = print,
    ) -> None:
        self.repo_root = repo_root
        self.python = python_executable
        self.git = git_executable if git_executable is not None else shutil.which("git")
        self._run = run
        self.requirements = (
            "requirements-windows.txt" if platform.startswith("win") else "requirements.txt"
        )
        self.log = log
        self._thread_lock = threading.Lock()

    # -- public API -----------------------------------------------------

    def update(self, *, allow_dependency_changes: bool = True) -> UpdateResult:
        """Try one update. Never raises; failures leave the checkout unchanged."""
        if not self.git:
            return UpdateResult("skipped", "git not found")
        if not self._thread_lock.acquire(blocking=False):
            return UpdateResult("skipped", "update already running")
        try:
            git_dir = self._git_dir()
            if git_dir is None:
                return UpdateResult("skipped", "not a git checkout")
            lock_path = os.path.join(git_dir, LOCK_FILENAME)
            if not _acquire_file_lock(lock_path):
                return UpdateResult("skipped", "another process is updating")
            try:
                return self._update(git_dir, allow_dependency_changes)
            finally:
                _release_file_lock(lock_path)
        except (OSError, subprocess.SubprocessError) as exc:
            return UpdateResult("skipped", f"updater error: {exc}")
        finally:
            self._thread_lock.release()

    def version(self) -> str:
        """Return ``<short sha> (<commit date>)`` for the current checkout."""
        if not self.git:
            return "unknown"
        try:
            result = self._git(["log", "-1", "--format=%h (%cs)"], timeout=10)
        except (OSError, subprocess.SubprocessError):
            return "unknown"
        return result.stdout.strip() if result.returncode == 0 else "unknown"

    # -- update flow ----------------------------------------------------

    def _update(self, git_dir: str, allow_dependency_changes: bool) -> UpdateResult:
        if self._git(["fetch", "--no-tags", "origin", "main"], timeout=60).returncode != 0:
            return UpdateResult("refused", "fetch failed")
        previous = self._rev_parse("HEAD")
        target = self._rev_parse("origin/main")
        if previous is None or target is None:
            return UpdateResult("refused", "could not resolve revisions")
        if previous == target:
            return UpdateResult("current")

        state = _load_state(git_dir)
        if target in state["bad_commits"]:
            return UpdateResult("refused", f"{target[:7]} failed its self-test before")
        ancestor = self._git(["merge-base", "--is-ancestor", "HEAD", "origin/main"])
        if ancestor.returncode != 0:
            return UpdateResult("refused", "local history diverged from origin/main")

        dependencies_changed = self._requirements_changed(previous, target)
        if dependencies_changed is None:
            return UpdateResult("refused", "could not compare requirements")
        if dependencies_changed and not allow_dependency_changes:
            return UpdateResult("refused", "dependency update deferred to next start")

        merge = self._git(["merge", "--ff-only", "origin/main"], timeout=60)
        if merge.returncode != 0:
            return UpdateResult("refused", "fast-forward failed")

        if dependencies_changed:
            self.log("[UPDATE] Installing updated dependencies...")
            if not self._install_requirements():
                return self._rollback(previous, restore_dependencies=True, reason="dependency install failed")
            # The app prefers system Edge/Chrome; the bundled browser is optional.
            self._call([self.python, "-m", "playwright", "install", "chromium"], timeout=900)

        if not self._self_test():
            state["bad_commits"] = (state["bad_commits"] + [target])[-MAX_BAD_COMMITS:]
            _save_state(git_dir, state)
            return self._rollback(
                previous,
                restore_dependencies=dependencies_changed,
                reason=f"self-test failed for {target[:7]}",
            )

        state["last_good"] = target
        _save_state(git_dir, state)
        return UpdateResult("updated", f"{previous[:7]}..{target[:7]}")

    def _rollback(self, previous: str, *, restore_dependencies: bool, reason: str) -> UpdateResult:
        self.log(f"[UPDATE] {reason}; returning to {previous[:7]}.")
        reset = self._git(["reset", "--keep", previous], timeout=60)
        if reset.returncode != 0:
            return UpdateResult("rolled_back", f"{reason}; reset to {previous[:7]} FAILED")
        if restore_dependencies and not self._install_requirements():
            return UpdateResult("rolled_back", f"{reason}; restoring previous dependencies FAILED")
        return UpdateResult("rolled_back", reason)

    # -- helpers --------------------------------------------------------

    def _requirements_changed(self, previous: str, target: str) -> bool | None:
        diff = self._git(["diff", "--quiet", previous, target, "--", *REQUIREMENT_FILES])
        if diff.returncode == 0:
            return False
        if diff.returncode == 1:
            return True
        return None

    def _install_requirements(self) -> bool:
        path = os.path.join(self.repo_root, self.requirements)
        command = [self.python, "-m", "pip", "install", "--disable-pip-version-check", "-r", path]
        return self._call(command, timeout=900)

    def _self_test(self) -> bool:
        env = dict(os.environ)
        env[DISABLE_ENV] = "1"
        command = [self.python, os.path.join(self.repo_root, "main.py"), "--self-test"]
        return self._call(command, timeout=180, env=env)

    def _call(self, command: Sequence[str], *, timeout: float, env: dict[str, str] | None = None) -> bool:
        try:
            result = self._run(
                list(command),
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0

    def _git(self, args: Sequence[str], *, timeout: float = 10) -> subprocess.CompletedProcess:
        assert self.git is not None
        return self._run(
            [self.git, *args],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def _rev_parse(self, ref: str) -> str | None:
        result = self._git(["rev-parse", ref])
        value = result.stdout.strip()
        return value if result.returncode == 0 and value else None

    def _git_dir(self) -> str | None:
        result = self._git(["rev-parse", "--absolute-git-dir"])
        value = result.stdout.strip()
        return value if result.returncode == 0 and value else None


def start_background_updater(
    updater: Updater,
    interval_seconds: float = UPDATE_INTERVAL_SECONDS,
) -> tuple[threading.Event, threading.Thread]:
    """Check for code-only updates periodically; they apply on next start."""
    stop_event = threading.Event()

    def loop() -> None:
        while not stop_event.wait(interval_seconds):
            result = updater.update(allow_dependency_changes=False)
            if result.status in ("updated", "rolled_back"):
                updater.log(f"[UPDATE] {result.status}: {result.detail}")

    thread = threading.Thread(target=loop, name="git-auto-updater", daemon=True)
    thread.start()
    return stop_event, thread


def _load_state(git_dir: str) -> dict:
    path = os.path.join(git_dir, STATE_FILENAME)
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = {}
    bad = data.get("bad_commits") if isinstance(data, dict) else None
    return {
        "bad_commits": [c for c in bad if isinstance(c, str)] if isinstance(bad, list) else [],
        "last_good": data.get("last_good") if isinstance(data, dict) else None,
    }


def _save_state(git_dir: str, state: dict) -> None:
    path = os.path.join(git_dir, STATE_FILENAME)
    temporary = path + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)
        os.replace(temporary, path)
    except OSError:
        pass


def _acquire_file_lock(path: str) -> bool:
    try:
        if time.time() - os.path.getmtime(path) > STALE_LOCK_SECONDS:
            os.remove(path)
    except OSError:
        pass
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return False
    os.write(descriptor, str(os.getpid()).encode("ascii"))
    os.close(descriptor)
    return True


def _release_file_lock(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
