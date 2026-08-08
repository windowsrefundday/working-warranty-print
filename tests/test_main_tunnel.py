import subprocess
import unittest
from unittest import mock

from main import (
    LOCAL_TUNNEL_ENTRYPOINT,
    is_valid_https_url,
    launch_https_tunnel,
    run_git_pull,
)


class HttpsTunnelTests(unittest.TestCase):
    def setUp(self):
        self.node = mock.patch("main.shutil.which", return_value="/runtime/node")
        self.node.start()

    def tearDown(self):
        self.node.stop()

    def test_accepts_only_https_url_with_hostname_and_pins_package(self):
        process = mock.MagicMock()
        process.stdout = iter(["your url is: https://scanner.example.test\n"])

        with mock.patch("main.subprocess.Popen", return_value=process) as popen:
            returned_process, public_url = launch_https_tunnel(9191)

        self.assertIs(returned_process, process)
        self.assertEqual(public_url, "https://scanner.example.test")
        self.assertEqual(
            popen.call_args.args[0],
            ["/runtime/node", LOCAL_TUNNEL_ENTRYPOINT, "--port", "9191"],
        )

    def test_rejects_tunnel_launch_when_node_is_missing(self):
        with (
            mock.patch("main.shutil.which", return_value=None),
            mock.patch("main.subprocess.Popen") as popen,
        ):
            with self.assertRaisesRegex(RuntimeError, "Node.js was not found"):
                launch_https_tunnel(9191)

        popen.assert_not_called()

    def test_rejects_non_https_url(self):
        process = mock.MagicMock()
        process.stdout = iter(["your url is: http://scanner.example.test\n"])
        process.poll.return_value = None

        with mock.patch("main.subprocess.Popen", return_value=process):
            with self.assertRaises(RuntimeError):
                launch_https_tunnel(9191)

        process.terminate.assert_called_once_with()

    def test_rejects_https_url_without_hostname(self):
        process = mock.MagicMock()
        process.stdout = iter(["your url is: https:///missing-host\n"])
        process.poll.return_value = None

        with mock.patch("main.subprocess.Popen", return_value=process):
            with self.assertRaises(RuntimeError):
                launch_https_tunnel(9191)

        process.terminate.assert_called_once_with()

    def test_waits_after_killing_stuck_process(self):
        process = mock.MagicMock()
        process.stdout = iter(())
        process.poll.return_value = None
        process.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="npx", timeout=3),
            0,
        ]

        with mock.patch("main.subprocess.Popen", return_value=process):
            with self.assertRaises(RuntimeError):
                launch_https_tunnel(9191, timeout_seconds=0.0)

        process.kill.assert_called_once_with()
        self.assertEqual(
            process.wait.call_args_list,
            [mock.call(timeout=3), mock.call()],
        )

    def test_reaps_tunnel_when_startup_is_interrupted(self):
        process = mock.MagicMock()
        process.poll.return_value = None

        with (
            mock.patch("main.subprocess.Popen", return_value=process),
            mock.patch("main.queue.Queue", side_effect=KeyboardInterrupt),
        ):
            with self.assertRaises(KeyboardInterrupt):
                launch_https_tunnel(9191)

        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=3)

    def test_url_validator_rejects_malformed_and_hostless_values(self):
        self.assertFalse(is_valid_https_url("https:///missing-host"))
        self.assertFalse(is_valid_https_url("https://[malformed"))
        self.assertFalse(is_valid_https_url("https://scanner.example.test:99999"))
        self.assertFalse(is_valid_https_url("http://scanner.example.test"))
        self.assertTrue(is_valid_https_url("https://scanner.example.test"))

    def test_git_updater_uses_fast_forward_only(self):
        completed = lambda args, code=0, output="": subprocess.CompletedProcess(
            args, code, stdout=output, stderr=""
        )
        with mock.patch(
            "main.subprocess.run",
            side_effect=[
                completed(["fetch"]),
                completed(["head"], output="old\n"),
                completed(["remote"], output="new\n"),
                completed(["ancestor"]),
                completed(["merge"], output="Updating old..new\n"),
            ],
        ) as run:
            self.assertTrue(run_git_pull())

        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0][1:], ["fetch", "--no-tags", "origin", "main"])
        self.assertEqual(commands[-1][1:], ["merge", "--ff-only", "origin/main"])
        self.assertNotIn("pull", [part for command in commands for part in command])

    def test_git_updater_refuses_diverged_history(self):
        completed = lambda args, code=0, output="": subprocess.CompletedProcess(
            args, code, stdout=output, stderr=""
        )
        with mock.patch(
            "main.subprocess.run",
            side_effect=[
                completed(["fetch"]),
                completed(["head"], output="local\n"),
                completed(["remote"], output="remote\n"),
                completed(["ancestor"], code=1),
            ],
        ) as run:
            self.assertFalse(run_git_pull())

        self.assertEqual(len(run.call_args_list), 4)


if __name__ == "__main__":
    unittest.main()
