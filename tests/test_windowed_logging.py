import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from step_to_acis.windowed_logging import windowed_streams


class WindowedLoggingTests(unittest.TestCase):
    def test_windowed_streams_preserve_output_and_traceback_and_restore_none(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(sys, "stdout", None), patch.object(sys, "stderr", None):
                with self.assertRaisesRegex(ValueError, "测试异常"):
                    with windowed_streams(root):
                        print("转换进度")
                        sys.stderr.write("错误详情\n")
                        raise ValueError("测试异常")
                self.assertIsNone(sys.stdout)
                self.assertIsNone(sys.stderr)
            logs = list((root / "logs").glob("*.log"))
            self.assertEqual(1, len(logs))
            content = logs[0].read_text(encoding="utf-8")
            for value in ("转换进度", "错误详情", "Traceback", "测试异常"):
                self.assertIn(value, content)

    def test_console_streams_are_unchanged_and_no_log_is_created(self):
        with tempfile.TemporaryDirectory() as directory:
            output, errors = io.StringIO(), io.StringIO()
            with patch.object(sys, "stdout", output), patch.object(sys, "stderr", errors):
                with windowed_streams(Path(directory)):
                    self.assertIs(output, sys.stdout)
                    self.assertIs(errors, sys.stderr)
            self.assertEqual([], list(Path(directory).iterdir()))

    def test_unwritable_state_falls_back_to_temp_and_keeps_existing_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocked = root / "blocked"
            blocked.write_text("file, not a directory", encoding="utf-8")
            output = io.StringIO()
            with patch.object(sys, "stdout", output), patch.object(sys, "stderr", None), patch(
                "step_to_acis.windowed_logging.tempfile.gettempdir", return_value=directory
            ):
                with windowed_streams(blocked):
                    self.assertIs(output, sys.stdout)
                    sys.stderr.write("fallback error\n")
            logs = list((root / "SpaceClaimStepToAcis" / "logs").glob("*.log"))
            self.assertEqual("fallback error\n", logs[0].read_text(encoding="utf-8"))
