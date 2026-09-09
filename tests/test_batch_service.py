import csv
import json
from pathlib import Path
import tempfile
import unittest

from step_to_acis.batch_service import BatchRequest, run_batch
from step_to_acis.models import ConversionResult, Status
from step_to_acis.probe_runner import CliCapabilityProfile


class RecordingReporter:
    def __init__(self):
        self.started = []
        self.statuses = []
        self.results = []

    def on_batch_started(self, total, run_directory):
        self.started.append((total, run_directory))

    def on_status(self, update):
        self.statuses.append(update)

    def on_result(self, result):
        self.results.append(result)


class BatchServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.input_dir = self.root / "input"
        self.output_dir = self.root / "output"
        self.input_dir.mkdir()
        self.executable = self.root / "SpaceClaim.exe"
        self.executable.write_bytes(b"fake")
        self.config_path = self.root / "config.json"
        self.profile_path = self.root / "profile.json"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_config(self, **updates):
        payload = {
            "spaceclaim_exe": str(self.executable),
            "input_dir": str(self.input_dir),
            "output_dir": str(self.output_dir),
        }
        payload.update(updates)
        self.config_path.write_text(json.dumps(payload), encoding="utf-8")

    def request(self):
        return BatchRequest(
            config_path=self.config_path,
            overrides={},
            capability_profile_path=self.profile_path,
        )

    @staticmethod
    def profile():
        return CliCapabilityProfile(
            run_script=True,
            script_api_v22=True,
            exit_after_script=True,
            headless=True,
            script_args=False,
            script_output=True,
            script_args_strategy="specialized_worker_literal",
        )

    def test_invalid_configuration_returns_preflight_without_supervisor(self):
        self.write_config(spaceclaim_exe=str(self.root / "missing.exe"))
        reporter = RecordingReporter()

        outcome = run_batch(
            self.request(),
            reporter,
            supervisor_factory=lambda **kwargs: self.fail("supervisor was created"),
        )

        self.assertEqual(2, outcome.exit_code)
        self.assertEqual("preflight", outcome.error_kind)
        self.assertIsNone(outcome.summary)
        self.assertIn("spaceclaim_exe", outcome.error_message)
        self.assertEqual([], reporter.started)

    def test_empty_input_writes_reports_and_skips_capability_loading(self):
        self.write_config()
        reporter = RecordingReporter()

        outcome = run_batch(
            self.request(),
            reporter,
            capability_profile_loader=lambda *args: self.fail("profile was loaded"),
        )

        self.assertEqual(0, outcome.exit_code)
        self.assertEqual("", outcome.error_kind)
        self.assertEqual((0, outcome.run_directory), reporter.started[0])
        self.assertEqual(1, len(reporter.started))
        self.assertEqual(0, outcome.summary.total)
        self.assertEqual((), outcome.results)
        self.assertTrue(outcome.csv_path.is_file())
        self.assertTrue(outcome.run_log_path.is_file())

    def test_mixed_supervisor_forwards_events_results_and_matching_reports(self):
        for name in ["a.stp", "b.step", "c.STP"]:
            (self.input_dir / name).write_bytes(b"STEP")
        self.write_config()
        reporter = RecordingReporter()

        class MixedSupervisor:
            def __init__(inner_self, **kwargs):
                inner_self.status_callback = kwargs["status_callback"]

            def run(inner_self, tasks, preflight, progress_callback):
                statuses = [Status.SUCCESS, Status.FAILED, Status.SKIPPED]
                results = []
                inner_self.status_callback(
                    {"kind": "process_started", "chunk_id": "chunk-0001", "pid": 1234}
                )
                for task, status in zip(tasks, statuses):
                    inner_self.status_callback(
                        {
                            "kind": "task_started",
                            "sequence": task.sequence,
                            "source_path": str(task.source_path),
                            "chunk_id": "chunk-0001",
                            "pid": 1234,
                        }
                    )
                    result = ConversionResult(
                        sequence=task.sequence,
                        task_id=task.task_id,
                        source_name=task.source_path.name,
                        source_path=str(task.source_path),
                        output_name=task.output_path.name,
                        output_path=str(task.output_path),
                        output_format=task.output_format.value,
                        source_size_bytes=task.source_size_bytes,
                        output_size_bytes=9 if status is Status.SUCCESS else 0,
                        start_time="start",
                        duration_seconds=1.0,
                        status=status,
                        error_message="fake failure" if status is Status.FAILED else "",
                    )
                    results.append(result)
                    progress_callback(result)
                inner_self.status_callback(
                    {
                        "kind": "process_finished",
                        "chunk_id": "chunk-0001",
                        "pid": 1234,
                        "returncode": 0,
                        "timed_out": False,
                    }
                )
                return list(reversed(results))

        outcome = run_batch(
            self.request(),
            reporter,
            capability_profile_loader=lambda *args: self.profile(),
            supervisor_factory=MixedSupervisor,
        )

        self.assertEqual(0, outcome.exit_code)
        self.assertEqual([(3, outcome.run_directory)], reporter.started)
        self.assertEqual(
            ["process_started", "task_started", "task_started", "task_started", "process_finished"],
            [update["kind"] for update in reporter.statuses],
        )
        self.assertEqual([Status.SUCCESS, Status.FAILED, Status.SKIPPED], [item.status for item in reporter.results])
        self.assertEqual(tuple(reporter.results), outcome.results)
        self.assertEqual([1, 2, 3], [item.sequence for item in outcome.results])
        self.assertEqual((3, 1, 1, 1), (outcome.summary.total, outcome.summary.success, outcome.summary.failed, outcome.summary.skipped))

        with outcome.csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            rows = list(csv.DictReader(csv_file))
        self.assertEqual(["Success", "Failed", "Skipped"], [row["Status"] for row in rows])
        run_log = outcome.run_log_path.read_text(encoding="utf-8")
        self.assertIn("Process started: pid=1234 chunk=chunk-0001", run_log)
        self.assertIn("Process finished: pid=1234 chunk=chunk-0001 exit_code=0 timed_out=False", run_log)
        self.assertIn("Summary: total=3 success=1 failed=1 skipped=1", run_log)


if __name__ == "__main__":
    unittest.main()
