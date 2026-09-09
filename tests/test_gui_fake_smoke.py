import csv
from pathlib import Path
import queue
import tempfile
import unittest

from step_to_acis.gui_models import GuiEvent, GuiRunState, reduce_gui_state
from step_to_acis.gui_reporting import QueueReporter
from step_to_acis.models import Status
from tools.smoke_gui_fake import prepare_fake_workspace, run_fake_batch


class GuiFakeSmokeTests(unittest.TestCase):
    def test_fake_full_chain_matches_gui_state_reports_and_preserves_sources(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "中文 fake workspace"
            paths = prepare_fake_workspace(workspace)
            before = {path: path.read_bytes() for path in paths["sources"]}
            events = queue.Queue()
            reporter = QueueReporter(events)

            outcome = run_fake_batch(workspace, reporter)
            events.put(
                GuiEvent(
                    "batch_completed",
                    {
                        "summary": outcome.summary,
                        "csv_path": outcome.csv_path,
                        "run_log_path": outcome.run_log_path,
                    },
                )
            )

            self.assertEqual(0, outcome.exit_code)
            self.assertEqual(
                [Status.SUCCESS, Status.FAILED, Status.SUCCESS],
                [result.status for result in outcome.results],
            )
            state = GuiRunState()
            observed = []
            while not events.empty():
                event = events.get_nowait()
                observed.append(event)
                state = reduce_gui_state(state, event)

            self.assertEqual((3, 2, 1, 0), (state.completed, state.success, state.failed, state.skipped))
            self.assertEqual("批次完成，但存在失败", state.message)
            status_payloads = [event.payload for event in observed if event.kind == "status"]
            self.assertTrue(any(item.get("kind") == "process_started" and item.get("pid") for item in status_payloads))
            self.assertTrue(any(item.get("kind") == "task_started" and item.get("chunk_id") for item in status_payloads))
            self.assertEqual("C success.STP", state.current_file)

            self.assertEqual(b"\xef\xbb\xbf", outcome.csv_path.read_bytes()[:3])
            with outcome.csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
                rows = list(csv.DictReader(csv_file))
            self.assertEqual(["Success", "Failed", "Success"], [row["Status"] for row in rows])
            self.assertEqual((2, 1, 0), (
                sum(row["Status"] == "Success" for row in rows),
                sum(row["Status"] == "Failed" for row in rows),
                sum(row["Status"] == "Skipped" for row in rows),
            ))

            run_log = outcome.run_log_path.read_text(encoding="utf-8")
            self.assertIn("Process started:", run_log)
            self.assertIn("Process finished:", run_log)
            self.assertIn("Summary: total=3 success=2 failed=1 skipped=0", run_log)
            self.assertEqual(before, {path: path.read_bytes() for path in paths["sources"]})


if __name__ == "__main__":
    unittest.main()
