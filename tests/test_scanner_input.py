import unittest

from interfaces.scanner_input import _read_windows_scanner


class WindowsScannerInputTests(unittest.TestCase):
    def test_enter_suffix_submits_scan(self):
        keys = iter("MXLTEST001\r")
        result = _read_windows_scanner(
            key_available=lambda: True,
            read_key=lambda: next(keys),
            pause=lambda _: None,
        )
        self.assertEqual(result, "MXLTEST001")

    def test_idle_timeout_submits_without_enter(self):
        keys = list("ABC123")
        clock = [0.0]

        def available():
            return bool(keys)

        def read_key():
            clock[0] += 0.01
            return keys.pop(0)

        def now():
            if not keys:
                clock[0] += 0.13
            return clock[0]

        result = _read_windows_scanner(
            key_available=available,
            read_key=read_key,
            now=now,
            pause=lambda _: None,
        )
        self.assertEqual(result, "ABC123")

    def test_ctrl_c_interrupts(self):
        with self.assertRaises(KeyboardInterrupt):
            _read_windows_scanner(
                key_available=lambda: True,
                read_key=lambda: "\x03",
                pause=lambda _: None,
            )


if __name__ == "__main__":
    unittest.main()
