from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from step_to_acis.discovery import build_plan
from step_to_acis.models import (
    AcisSettings,
    ConverterConfig,
    OutputFormat,
    OverwritePolicy,
    Status,
)
from step_to_acis.protocol import EventReadResult, ProtocolError, read_complete_events
from step_to_acis.supervisor import BatchSupervisor

class FakeProcess:
    def __init__(self):
        self.pid = 4321
        self.running = True
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0

    def poll(self):
        return None if self.running else -15

    def terminate(self):
        self.terminate_calls += 1
        self.running = False

    def kill(self):
        self.kill_calls += 1
        self.running = False

    def wait(self, timeout=None):
        self.wait_calls += 1
        self.running = False
        return -15


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.input_dir = self.root / "input"
        self.output_dir = self.root / "output"
        self.run_dir = self.root / "run"
        self.input_dir.mkdir()
        self.executable = self.root / "SpaceClaim.exe"
        self.executable.write_bytes(b"fake")
        repository_root = Path(__file__).resolve().parents[1]
        self.worker_template = repository_root / "tools" / "fake_spaceclaim.py"
        self.commands = []
        self.status_updates = []

    def tearDown(self):
        self.temporary_directory.cleanup()

    def config(self, **updates):
        values = {
            "spaceclaim_exe": self.executable,
            "input_dir": self.input_dir,
            "output_dir": self.output_dir,
            "recursive": False,
            "acis": AcisSettings((OutputFormat.SAB,), "current_spaceclaim_default", "Millimeters"),
            "overwrite_policy": OverwritePolicy.SKIP,
            "chunk_size": 2,
            "heartbeat_timeout_seconds": 2.0,
            "retry_count": 0,
            "preserve_relative_directories": True,
            "long_path_warning_threshold": 240,
        }
        values.update(updates)
        return ConverterConfig(**values)

    def source(self, name, mode="success"):
        path = self.input_dir / name
        path.write_text("MODE:{}".format(mode), encoding="utf-8")
        return path

    def command_factory(self, worker, script_output):
        command = [sys.executable, str(worker)]
        self.commands.append(command)
        return command

    def run_batch(self, config):
        tasks, preflight = build_plan(config)
        progress = []
        supervisor = BatchSupervisor(
            config=config,
            run_directory=self.run_dir,
            worker_template=self.worker_template,
            command_factory=self.command_factory,
            poll_interval_seconds=0.02,
            status_callback=self.status_updates.append,
        )
        results = supervisor.run(tasks, preflight, progress.append)
        return results, progress

    def test_chunks_are_bounded_and_progress_reports_each_terminal_result(self):
        for index in range(5):
            self.source("part-{}.stp".format(index))

        results, progress = self.run_batch(self.config(chunk_size=2))

        self.assertEqual(5, len(results))
        self.assertTrue(all(result.status is Status.SUCCESS for result in results))
        self.assertEqual(3, len(self.commands))
        self.assertEqual(5, len(progress))
        self.assertEqual([1, 2, 3, 4, 5], [result.sequence for result in results])

    def test_status_updates_expose_process_and_current_task(self):
        source = self.source("当前模型.stp")

        self.run_batch(self.config(chunk_size=1))

        process_updates = [item for item in self.status_updates if item["kind"] == "process_started"]
        task_updates = [item for item in self.status_updates if item["kind"] == "task_started"]
        self.assertEqual(1, len(process_updates))
        self.assertGreater(process_updates[0]["pid"], 0)
        self.assertEqual(str(source), task_updates[0]["source_path"])
        self.assertEqual("chunk-0001", task_updates[0]["chunk_id"])

    def test_transient_permission_error_while_worker_runs_is_retried(self):
        self.source("part.stp")
        read_attempts = 0

        def read_with_one_transient_denial(path):
            nonlocal read_attempts
            read_attempts += 1
            if read_attempts == 1:
                error = ProtocolError(
                    "cannot read events: [Errno 13] Permission denied"
                )
                error.__cause__ = PermissionError(13, "Permission denied", str(path))
                raise error
            return read_complete_events(path)

        with patch(
            "step_to_acis.supervisor.read_complete_events",
            side_effect=read_with_one_transient_denial,
        ):
            results, progress = self.run_batch(self.config(chunk_size=1))

        self.assertEqual([Status.SUCCESS], [result.status for result in results])
        self.assertEqual(results, progress)
        self.assertGreaterEqual(read_attempts, 2)

    def test_persistent_permission_error_still_triggers_heartbeat_timeout(self):
        self.source("part.stp")
        config = self.config(heartbeat_timeout_seconds=2.0)
        tasks, _ = build_plan(config)
        process = FakeProcess()
        running_reads = 0

        def deny_while_running(path):
            nonlocal running_reads
            if process.running:
                running_reads += 1
                if running_reads > 1:
                    raise AssertionError("timeout check was bypassed")
                error = ProtocolError("cannot read events: permission denied")
                error.__cause__ = PermissionError(13, "Permission denied", str(path))
                raise error
            return EventReadResult((), "", ())

        supervisor = BatchSupervisor(
            config=config,
            run_directory=self.run_dir,
            worker_template=self.worker_template,
            command_factory=self.command_factory,
            poll_interval_seconds=0.0,
        )
        with patch("step_to_acis.supervisor.subprocess.Popen", return_value=process), patch(
            "step_to_acis.supervisor.read_complete_events",
            side_effect=deny_while_running,
        ), patch("step_to_acis.supervisor.time.monotonic", side_effect=[0.0, 3.0]):
            outcome = supervisor._run_chunk(1, tasks)

        self.assertTrue(outcome["timed_out"])
        self.assertEqual(1, running_reads)
        self.assertEqual(1, process.terminate_calls)
        self.assertGreaterEqual(process.wait_calls, 1)

    def test_active_protocol_error_terminates_and_reaps_worker_before_reraise(self):
        self.source("part.stp")
        config = self.config()
        tasks, _ = build_plan(config)
        process = FakeProcess()
        supervisor = BatchSupervisor(
            config=config,
            run_directory=self.run_dir,
            worker_template=self.worker_template,
            command_factory=self.command_factory,
            poll_interval_seconds=0.0,
        )

        with patch("step_to_acis.supervisor.subprocess.Popen", return_value=process), patch(
            "step_to_acis.supervisor.read_complete_events",
            side_effect=ProtocolError("event line 1 is invalid JSON"),
        ):
            with self.assertRaisesRegex(ProtocolError, "invalid JSON"):
                supervisor._run_chunk(1, tasks)

        self.assertEqual(1, process.terminate_calls)
        self.assertGreaterEqual(process.wait_calls, 1)
        self.assertFalse(process.running)

    def test_single_failed_task_does_not_stop_later_tasks(self):
        self.source("a.stp")
        self.source("b.stp", "failed")
        self.source("c.step")

        results, _ = self.run_batch(self.config(chunk_size=3))

        self.assertEqual(
            [Status.SUCCESS, Status.FAILED, Status.SUCCESS],
            [result.status for result in results],
        )

    def test_process_crash_fails_current_task_and_reschedules_remainder(self):
        self.source("a-crash.stp", "crash")
        self.source("b-after.stp")

        results, _ = self.run_batch(self.config(chunk_size=2))

        self.assertEqual([Status.FAILED, Status.SUCCESS], [item.status for item in results])
        self.assertGreaterEqual(len(self.commands), 2)
        self.assertIn("worker process", results[0].error_message)

    def test_timeout_terminates_hung_worker_and_continues(self):
        self.source("a-hang.stp", "hang")
        self.source("b-after.stp")

        results, _ = self.run_batch(
            self.config(chunk_size=2, heartbeat_timeout_seconds=0.2)
        )

        self.assertEqual([Status.FAILED, Status.SUCCESS], [item.status for item in results])
        self.assertIn("timeout", results[0].error_message)

    def test_close_fatal_preserves_completed_result_and_restarts_remainder(self):
        self.source("a-close.stp", "close-fatal")
        self.source("b-after.stp")

        results, _ = self.run_batch(self.config(chunk_size=2))

        self.assertEqual([Status.SUCCESS, Status.SUCCESS], [item.status for item in results])
        self.assertGreaterEqual(len(self.commands), 2)

    def test_failed_overwrite_preserves_old_output(self):
        self.source("part.stp", "failed")
        self.output_dir.mkdir()
        output = self.output_dir / "part.sab"
        output.write_bytes(b"old-output")

        results, _ = self.run_batch(
            self.config(overwrite_policy=OverwritePolicy.OVERWRITE)
        )

        self.assertEqual(Status.FAILED, results[0].status)
        self.assertEqual(b"old-output", output.read_bytes())

    def test_successful_overwrite_atomically_replaces_old_output(self):
        self.source("part.stp")
        self.output_dir.mkdir()
        output = self.output_dir / "part.sab"
        output.write_bytes(b"old-output")

        results, _ = self.run_batch(
            self.config(overwrite_policy=OverwritePolicy.OVERWRITE)
        )

        self.assertEqual(Status.SUCCESS, results[0].status)
        self.assertEqual(b"FAKE-ACIS", output.read_bytes())

    def test_retry_count_one_retries_once_without_duplicate_result(self):
        self.source("part.stp", "fail-once")

        results, _ = self.run_batch(self.config(retry_count=1, chunk_size=1))

        self.assertEqual(1, len(results))
        self.assertEqual(Status.SUCCESS, results[0].status)
        self.assertEqual(2, len(self.commands))

    def test_preflight_skip_does_not_launch_worker(self):
        self.source("part.stp")
        self.output_dir.mkdir()
        (self.output_dir / "part.sab").write_bytes(b"existing")

        results, _ = self.run_batch(self.config())

        self.assertEqual(Status.SKIPPED, results[0].status)
        self.assertEqual([], self.commands)
