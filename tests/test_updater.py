import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from updater import STATE_FILENAME, Updater

GOOD_MAIN = "import sys\nsys.exit(0)\n"
BROKEN_MAIN = "import sys\nsys.exit(1)\n"
SYNTAX_ERROR_MAIN = "def broken(:\n"


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class PipStub:
    """Pass git and self-test commands through; record and stub pip calls."""

    def __init__(self, pip_exit_codes=()):
        self.pip_exit_codes = list(pip_exit_codes)
        self.pip_calls: list[list[str]] = []

    def __call__(self, command, **kwargs):
        if "pip" in command or "playwright" in command:
            self.pip_calls.append(command)
            code = self.pip_exit_codes.pop(0) if self.pip_exit_codes else 0
            return subprocess.CompletedProcess(command, code, stdout="", stderr="")
        return subprocess.run(command, **kwargs)


@unittest.skipUnless(shutil.which("git"), "git is required")
class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.origin = self.temp / "origin.git"
        self.author = self.temp / "author"
        self.client = self.temp / "client"
        git(self.temp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(self.temp, "clone", "-q", str(self.origin), str(self.author))
        self._configure(self.author)
        self.publish({"main.py": GOOD_MAIN, "requirements.txt": "# v1\n"})
        git(self.temp, "clone", "-q", str(self.origin), str(self.client))
        self._configure(self.client)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def _configure(self, repo: Path) -> None:
        git(repo, "config", "user.email", "test@example.test")
        git(repo, "config", "user.name", "Test")
        git(repo, "checkout", "-q", "-B", "main")

    def publish(self, files: dict[str, str]) -> str:
        for name, content in files.items():
            (self.author / name).write_text(content, encoding="utf-8")
        git(self.author, "add", "-A")
        git(self.author, "commit", "-q", "-m", "change")
        git(self.author, "push", "-q", "origin", "main")
        return git(self.author, "rev-parse", "HEAD")

    def updater(self, stub: PipStub | None = None) -> Updater:
        return Updater(
            str(self.client),
            python_executable=sys.executable,
            run=stub or PipStub(),
            platform="linux",
            log=lambda _message: None,
        )

    def client_head(self) -> str:
        return git(self.client, "rev-parse", "HEAD")

    def test_reports_current_when_nothing_to_pull(self):
        self.assertEqual(self.updater().update().status, "current")

    def test_applies_good_code_update_without_touching_dependencies(self):
        stub = PipStub()
        target = self.publish({"main.py": GOOD_MAIN + "# v2\n"})

        result = self.updater(stub).update()

        self.assertEqual(result.status, "updated")
        self.assertEqual(self.client_head(), target)
        self.assertEqual(stub.pip_calls, [])

    def test_rolls_back_commit_that_fails_self_test_and_never_retries_it(self):
        previous = self.client_head()
        bad = self.publish({"main.py": BROKEN_MAIN})

        first = self.updater().update()
        second = self.updater().update()

        self.assertEqual(first.status, "rolled_back")
        self.assertEqual(self.client_head(), previous)
        self.assertEqual(second.status, "refused")
        self.assertIn(bad[:7], second.detail)
        self.assertEqual((self.client / "main.py").read_text(), GOOD_MAIN)

    def test_rolls_back_syntax_error_and_accepts_later_fix(self):
        previous = self.client_head()
        self.publish({"main.py": SYNTAX_ERROR_MAIN})
        self.assertEqual(self.updater().update().status, "rolled_back")
        self.assertEqual(self.client_head(), previous)

        fix = self.publish({"main.py": GOOD_MAIN + "# fixed\n"})

        self.assertEqual(self.updater().update().status, "updated")
        self.assertEqual(self.client_head(), fix)

    def test_installs_changed_requirements_before_self_test(self):
        stub = PipStub()
        target = self.publish({"requirements.txt": "# v2\n"})

        result = self.updater(stub).update()

        self.assertEqual(result.status, "updated")
        self.assertEqual(self.client_head(), target)
        pip_installs = [c for c in stub.pip_calls if "pip" in c]
        self.assertEqual(len(pip_installs), 1)
        self.assertTrue(pip_installs[0][-1].endswith("requirements.txt"))

    def test_uses_windows_requirements_on_windows(self):
        stub = PipStub()
        self.publish({"requirements.txt": "# v2\n"})
        updater = Updater(
            str(self.client),
            python_executable=sys.executable,
            run=stub,
            platform="win32",
            log=lambda _message: None,
        )

        updater.update()

        self.assertTrue(stub.pip_calls[0][-1].endswith("requirements-windows.txt"))

    def test_blocked_pip_rolls_back_and_retries_on_next_start(self):
        previous = self.client_head()
        target = self.publish({"requirements.txt": "# v2\n"})
        blocked = PipStub(pip_exit_codes=[1, 0])

        result = self.updater(blocked).update()

        self.assertEqual(result.status, "rolled_back")
        self.assertEqual(self.client_head(), previous)
        self.assertEqual((self.client / "requirements.txt").read_text(), "# v1\n")
        # Previous requirements are reinstalled after the failed install.
        self.assertEqual(len([c for c in blocked.pip_calls if "pip" in c]), 2)
        # A network failure is not the commit's fault; it is retried later.
        self.assertEqual(self.updater().update().status, "updated")
        self.assertEqual(self.client_head(), target)

    def test_background_mode_defers_dependency_changes(self):
        previous = self.client_head()
        self.publish({"requirements.txt": "# v2\n"})

        result = self.updater().update(allow_dependency_changes=False)

        self.assertEqual(result.status, "refused")
        self.assertEqual(self.client_head(), previous)

    def test_refuses_diverged_history_and_keeps_local_commit(self):
        (self.client / "local.txt").write_text("local\n", encoding="utf-8")
        git(self.client, "add", "local.txt")
        git(self.client, "commit", "-q", "-m", "local")
        local = self.client_head()
        self.publish({"main.py": GOOD_MAIN + "# v2\n"})

        result = self.updater().update()

        self.assertEqual(result.status, "refused")
        self.assertEqual(self.client_head(), local)

    def test_rollback_keeps_uncommitted_local_edits(self):
        (self.client / "notes.txt").write_text("keep me\n", encoding="utf-8")
        self.publish({"main.py": BROKEN_MAIN})

        self.assertEqual(self.updater().update().status, "rolled_back")
        self.assertEqual((self.client / "notes.txt").read_text(), "keep me\n")

    def test_corrupt_state_file_is_ignored(self):
        git_dir = git(self.client, "rev-parse", "--absolute-git-dir")
        Path(git_dir, STATE_FILENAME).write_text("{not json", encoding="utf-8")
        self.publish({"main.py": GOOD_MAIN + "# v2\n"})

        self.assertEqual(self.updater().update().status, "updated")

    def test_fetch_failure_leaves_checkout_alone(self):
        previous = self.client_head()
        git(self.client, "remote", "set-url", "origin", str(self.temp / "missing.git"))

        result = self.updater().update()

        self.assertEqual(result.status, "refused")
        self.assertEqual(self.client_head(), previous)

    def test_missing_git_is_skipped(self):
        updater = Updater(str(self.client), git_executable="", log=lambda _m: None)
        self.assertEqual(updater.update().status, "skipped")

    def test_version_reports_short_sha(self):
        self.assertTrue(self.updater().version().startswith(self.client_head()[:7]))


if __name__ == "__main__":
    unittest.main()
