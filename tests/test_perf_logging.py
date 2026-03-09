import os
import unittest
from unittest.mock import patch

from perf_logging import perf_log, perf_logging_enabled


class PerfLoggingTests(unittest.TestCase):
    def test_perf_logging_enabled_default_true(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(perf_logging_enabled())

    def test_perf_logging_enabled_false_values(self):
        for value in ["0", "false", "False", "off", "no"]:
            with patch.dict(os.environ, {"PERF_LOG_ENABLED": value}, clear=True):
                self.assertFalse(perf_logging_enabled())

    def test_perf_log_respects_flag(self):
        with patch("builtins.print") as mocked_print:
            with patch.dict(os.environ, {"PERF_LOG_ENABLED": "0"}, clear=True):
                perf_log("PERF teste")
            mocked_print.assert_not_called()

        with patch("builtins.print") as mocked_print:
            with patch.dict(os.environ, {"PERF_LOG_ENABLED": "1"}, clear=True):
                perf_log("PERF teste")
            mocked_print.assert_called_once_with("PERF teste")


if __name__ == "__main__":
    unittest.main()
