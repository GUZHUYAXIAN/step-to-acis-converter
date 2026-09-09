import io
from pathlib import Path
import unittest
from unittest.mock import patch

from step_to_acis.batch_service import BatchOutcome
from step_to_acis.reporting import RunSummary
from tests.test_gui_worker import ConverterGuiWorkerTests


class GuiConsoleOutcomeTests(ConverterGuiWorkerTests):
    def run_with_outcome(self, outcome):
        gui, _, _ = self.make_worker_gui(lambda request, reporter: outcome)
        output = io.StringIO()
        errors = io.StringIO()
        with patch("step_to_acis.gui.sys.stdout", output), patch(
            "step_to_acis.gui.sys.stderr", errors
        ):
            gui._run_worker()
        return output.getvalue(), errors.getvalue()

    def test_partial_failure_prints_summary_paths_and_warning_to_visible_console(self):
        csv_path = Path(r"E:\logs\conversion_log.csv")
        run_log_path = Path(r"E:\logs\conversion_run.txt")
        outcome = BatchOutcome(
            0,
            RunSummary(3, 2, 1, 0, 30.0),
            (),
            Path(r"E:\logs"),
            csv_path,
            run_log_path,
            "",
            "",
        )

        output, errors = self.run_with_outcome(outcome)

        self.assertEqual("", errors)
        self.assertIn("总文件数：3", output)
        self.assertIn("成功：2", output)
        self.assertIn("失败：1", output)
        self.assertIn(str(csv_path), output)
        self.assertIn(str(run_log_path), output)
        self.assertIn("存在 1 个转换失败文件", output)

    def test_fatal_outcome_prints_classified_error_and_log_path_to_stderr(self):
        run_log_path = Path(r"E:\logs\conversion_run.txt")
        outcome = BatchOutcome(
            4,
            None,
            (),
            Path(r"E:\logs"),
            Path(r"E:\logs\conversion_log.csv"),
            run_log_path,
            "fatal",
            "controller failed",
        )

        output, errors = self.run_with_outcome(outcome)

        self.assertEqual("", output)
        self.assertIn("批处理致命错误", errors)
        self.assertIn("controller failed", errors)
        self.assertIn(str(run_log_path), errors)


if __name__ == "__main__":
    unittest.main()
