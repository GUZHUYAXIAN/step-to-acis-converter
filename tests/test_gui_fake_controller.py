from dataclasses import replace
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from step_to_acis.models import Status
from tests.test_gui import FakeRoot, FakeThread
from tests.test_gui_worker import StateRecordingView
from tools.smoke_gui_fake import build_fake_gui


class GuiFakeControllerSmokeTests(unittest.TestCase):
    def test_controller_honors_form_request_and_reaches_partial_completion(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "中文 fake workspace"
            root = FakeRoot()
            threads = []

            def thread_factory(**kwargs):
                thread = FakeThread(**kwargs)
                threads.append(thread)
                return thread

            gui = build_fake_gui(
                root,
                workspace,
                view_factory=StateRecordingView,
                thread_factory=thread_factory,
            )
            gui.view.values = replace(
                gui.view.values,
                output_format="SAT",
                recursive=True,
            )

            gui.start_conversion()
            self.assertEqual(1, len(threads))
            with patch("step_to_acis.gui.sys.stdout", io.StringIO()), patch(
                "step_to_acis.gui.sys.stderr", io.StringIO()
            ):
                threads[0].target()
            gui.poll_events()

            results = [
                event.payload["result"]
                for event in gui.view.event_history
                if event.kind == "result"
            ]
            self.assertEqual(3, len(results))
            self.assertEqual(["SAT", "SAT", "SAT"], [item.output_format for item in results])
            self.assertTrue(all(Path(item.output_path).suffix.lower() == ".sat" for item in results))
            self.assertEqual([Status.SUCCESS, Status.FAILED, Status.SUCCESS], [item.status for item in results])
            self.assertEqual((3, 2, 1, 0), (gui.state.completed, gui.state.success, gui.state.failed, gui.state.skipped))
            self.assertEqual("批次完成，但存在失败", gui.state.message)
            self.assertFalse(gui._worker_active)
