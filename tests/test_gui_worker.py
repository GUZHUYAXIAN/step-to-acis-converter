from pathlib import Path
import unittest

from step_to_acis.batch_service import BatchOutcome, BatchRequest
from step_to_acis.cli import ConsoleReporter
from step_to_acis.gui import ConverterGui
from step_to_acis.gui_models import GuiEvent
from step_to_acis.gui_reporting import CompositeReporter, QueueReporter
from step_to_acis.models import ConversionResult, Status
from step_to_acis.reporting import RunSummary
from tests.test_gui import ConverterGuiConstructionTests, FakeRoot, FakeThread, FakeView


class StateRecordingView(FakeView):
    def __init__(self, root, values):
        super().__init__(root, values)
        self.state_history = []
        self.event_history = []

    def update_state(self, state):
        self.state_history.append(state)

    def append_event(self, event):
        self.event_history.append(event)


class ConverterGuiWorkerTests(ConverterGuiConstructionTests):
    def make_worker_gui(self, batch_runner, *, worker_template_path=None):
        root = FakeRoot()
        threads = []

        def thread_factory(**kwargs):
            thread = FakeThread(**kwargs)
            threads.append(thread)
            return thread

        gui = ConverterGui(
            root,
            config_path=self.config_path,
            capability_profile_path=self.profile_path,
            settings_path=self.settings_path,
            worker_template_path=worker_template_path,
            batch_runner=batch_runner,
            thread_factory=thread_factory,
            view_factory=StateRecordingView,
        )
        return gui, root, threads

    def success_outcome(self):
        return BatchOutcome(
            exit_code=0,
            summary=RunSummary(0, 0, 0, 0, 0.25),
            results=(),
            run_directory=self.root_dir / "run",
            csv_path=self.root_dir / "run" / "conversion_log.csv",
            run_log_path=self.root_dir / "run" / "conversion_run.txt",
            error_kind="",
            error_message="",
        )

    @staticmethod
    def sample_result():
        return ConversionResult(
            sequence=1,
            task_id="task-1",
            source_name="中文.stp",
            source_path=r"E:\输入\中文.stp",
            output_name="中文.sab",
            output_path=r"E:\输出\中文.sab",
            output_format="SAB",
            source_size_bytes=10,
            output_size_bytes=20,
            start_time="start",
            duration_seconds=1.0,
            status=Status.SUCCESS,
            error_message="",
        )

    def test_worker_builds_request_and_composite_reporter_then_completes_once(self):
        calls = []
        worker_template = self.root_dir / "bundled" / "worker_v22.py"

        def runner(request, reporter):
            calls.append((request, reporter))
            return self.success_outcome()

        gui, _, _ = self.make_worker_gui(
            runner, worker_template_path=worker_template
        )

        gui._run_worker()

        self.assertEqual(1, len(calls))
        request, reporter = calls[0]
        self.assertIsInstance(request, BatchRequest)
        self.assertEqual(self.config_path, request.config_path)
        self.assertEqual(self.profile_path, request.capability_profile_path)
        self.assertEqual(worker_template, request.worker_template_path)
        self.assertEqual(["SAB"], request.overrides["output_formats"])
        self.assertIsInstance(reporter, CompositeReporter)
        self.assertIsInstance(reporter.reporters[0], ConsoleReporter)
        self.assertIsInstance(reporter.reporters[1], QueueReporter)
        events = list(gui.event_queue.queue)
        self.assertEqual(["batch_completed"], [event.kind for event in events])
        self.assertEqual(self.success_outcome().csv_path, events[0].payload["csv_path"])
        self.assertEqual(self.success_outcome().run_log_path, events[0].payload["run_log_path"])

    def test_nonzero_outcome_emits_one_batch_failed_event(self):
        outcome = BatchOutcome(4, None, (), None, None, None, "fatal", "service failed")
        gui, _, _ = self.make_worker_gui(lambda request, reporter: outcome)

        gui._run_worker()

        events = list(gui.event_queue.queue)
        self.assertEqual(["batch_failed"], [event.kind for event in events])
        self.assertEqual("service failed", events[0].payload["error_message"])

    def test_unexpected_worker_exception_emits_one_batch_failed_event(self):
        def explode(request, reporter):
            raise RuntimeError("unexpected failure")

        gui, _, _ = self.make_worker_gui(explode)

        gui._run_worker()

        events = list(gui.event_queue.queue)
        self.assertEqual(["batch_failed"], [event.kind for event in events])
        self.assertEqual("unexpected failure", events[0].payload["error_message"])

    def test_poll_drains_all_events_updates_view_reenables_and_reschedules(self):
        gui, root, _ = self.make_worker_gui(lambda request, reporter: self.success_outcome())
        gui._worker_active = True
        gui.event_queue.put(GuiEvent("batch_started", {"total": 1}))
        gui.event_queue.put(
            GuiEvent(
                "status",
                {
                    "kind": "task_started",
                    "source_path": r"E:\输入\中文.stp",
                    "pid": 1234,
                    "chunk_id": "chunk-0001",
                },
            )
        )
        gui.event_queue.put(GuiEvent("result", {"result": self.sample_result()}))
        gui.event_queue.put(
            GuiEvent(
                "batch_completed",
                {"csv_path": Path("conversion.csv"), "run_log_path": Path("run.txt")},
            )
        )

        gui.poll_events()

        self.assertTrue(gui.event_queue.empty())
        self.assertEqual(4, len(gui.view.state_history))
        self.assertEqual(4, len(gui.view.event_history))
        self.assertEqual("批次转换完成", gui.state.message)
        self.assertFalse(gui._worker_active)
        self.assertEqual([True], gui.view.enabled_history)
        self.assertEqual(1, len(root.after_calls))
        self.assertEqual(100, root.after_calls[0][0])

    def test_close_idle_destroys_but_running_close_is_blocked(self):
        gui, root, _ = self.make_worker_gui(lambda request, reporter: self.success_outcome())

        gui.request_close()
        self.assertEqual(1, root.destroy_calls)

        gui._worker_active = True
        gui.request_close()
        self.assertEqual(1, root.destroy_calls)
        self.assertIn("等待", gui.view.errors[-1])


if __name__ == "__main__":
    unittest.main()
