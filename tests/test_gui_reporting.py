from pathlib import Path
import queue
import unittest

from step_to_acis.gui_models import GuiEvent
from step_to_acis.gui_reporting import CompositeReporter, QueueReporter
from step_to_acis.models import ConversionResult, Status


def sample_result(status=Status.SUCCESS):
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
        duration_seconds=1.5,
        status=status,
        error_message="",
    )


class QueueReporterTests(unittest.TestCase):
    def setUp(self):
        self.events = queue.Queue()
        self.reporter = QueueReporter(self.events)

    def drain(self):
        items = []
        while not self.events.empty():
            items.append(self.events.get_nowait())
        return items

    def test_batch_started_enqueues_total_and_run_directory(self):
        run_directory = Path(r"E:\logs\run")

        self.reporter.on_batch_started(3, run_directory)

        self.assertEqual(
            [GuiEvent("batch_started", {"total": 3, "run_directory": run_directory})],
            self.drain(),
        )

    def test_status_events_retain_payload_without_dropping_kinds(self):
        statuses = [
            {
                "kind": "task_started",
                "sequence": 2,
                "source_path": r"E:\输入\中文.stp",
                "pid": 1234,
                "chunk_id": "chunk-0001",
            },
            {"kind": "process_started", "pid": 1234, "chunk_id": "chunk-0001"},
            {
                "kind": "process_finished",
                "pid": 1234,
                "chunk_id": "chunk-0001",
                "returncode": 0,
                "timed_out": False,
            },
            {
                "kind": "worker_fatal",
                "chunk_id": "chunk-0001",
                "error_message": "fatal",
            },
        ]

        for status in statuses:
            self.reporter.on_status(status)

        events = self.drain()
        self.assertEqual(["status"] * 4, [event.kind for event in events])
        self.assertEqual(statuses, [event.payload for event in events])

    def test_each_terminal_result_enqueues_the_real_result(self):
        result = sample_result(Status.FAILED)

        self.reporter.on_result(result)

        event = self.events.get_nowait()
        self.assertEqual("result", event.kind)
        self.assertIs(result, event.payload["result"])
        self.assertTrue(self.events.empty())

    def test_composite_reporter_invokes_each_reporter_once_in_order(self):
        calls = []

        class Recorder:
            def __init__(self, name):
                self.name = name

            def on_batch_started(self, total, run_directory):
                calls.append((self.name, "started", total))

            def on_status(self, update):
                calls.append((self.name, "status", update["kind"]))

            def on_result(self, result):
                calls.append((self.name, "result", result.status.value))

        composite = CompositeReporter(Recorder("console"), Recorder("queue"))
        result = sample_result()

        composite.on_batch_started(1, Path("run"))
        composite.on_status({"kind": "task_started"})
        composite.on_result(result)

        self.assertEqual(
            [
                ("console", "started", 1),
                ("queue", "started", 1),
                ("console", "status", "task_started"),
                ("queue", "status", "task_started"),
                ("console", "result", "Success"),
                ("queue", "result", "Success"),
            ],
            calls,
        )


if __name__ == "__main__":
    unittest.main()
