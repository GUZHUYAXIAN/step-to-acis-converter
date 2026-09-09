from collections import deque
from dataclasses import replace
from pathlib import Path
import os
import subprocess
import time
from typing import Callable, Sequence

from .discovery import assert_safe_output
from .models import ConversionResult, ConversionTask, ConverterConfig, Status
from .protocol import ProtocolError, read_complete_events, write_manifest
from .spaceclaim_command import specialize_worker_template


def _is_transient_event_read_error(error: ProtocolError) -> bool:
    cause = error.__cause__
    while cause is not None:
        if isinstance(cause, PermissionError):
            return True
        cause = cause.__cause__
    return False


def _terminate_process(process) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


class SupervisorError(RuntimeError):
    pass


class BatchSupervisor:
    def __init__(
        self,
        config: ConverterConfig,
        run_directory: Path,
        worker_template: Path,
        command_factory: Callable[[Path, Path], list[str]],
        poll_interval_seconds: float = 0.25,
        status_callback: Callable[[dict], None] | None = None,
    ):
        self.config = config
        self.run_directory = run_directory.resolve()
        self.worker_template = worker_template
        self.command_factory = command_factory
        self.poll_interval_seconds = poll_interval_seconds
        self.status_callback = status_callback or (lambda update: None)

    def run(
        self,
        tasks: Sequence[ConversionTask],
        preflight_results: Sequence[ConversionResult],
        progress_callback: Callable[[ConversionResult], None],
    ) -> list[ConversionResult]:
        self.run_directory.mkdir(parents=True, exist_ok=True)
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        pending = deque(tasks)
        results = list(preflight_results)
        for result in preflight_results:
            progress_callback(result)
        source_paths = {task.source_path for task in tasks}
        chunk_number = 0
        while pending:
            chunk_number += 1
            chunk = [pending.popleft() for _ in range(min(self.config.chunk_size, len(pending)))]
            outcome = self._run_chunk(chunk_number, chunk)
            terminal_events = {
                event["task_id"]: event
                for event in outcome["events"]
                if event.get("event") == "task_finished"
            }
            completed_ids = set()
            retry_tasks = []
            for task in chunk:
                event = terminal_events.get(task.task_id)
                if event is None:
                    continue
                completed_ids.add(task.task_id)
                result = self._result_from_event(task, event, source_paths)
                if result.status is Status.FAILED and task.attempt < self.config.retry_count:
                    retry_tasks.append(replace(task, attempt=task.attempt + 1))
                else:
                    results.append(result)
                    progress_callback(result)

            unfinished = [task for task in chunk if task.task_id not in completed_ids]
            started_ids = [
                event.get("task_id")
                for event in outcome["events"]
                if event.get("event") == "task_started"
                and event.get("task_id") not in completed_ids
            ]
            if unfinished and started_ids:
                current_id = started_ids[-1]
                current = next(task for task in unfinished if task.task_id == current_id)
                unfinished.remove(current)
                failure = self._process_failure_result(current, outcome)
                if current.attempt < self.config.retry_count:
                    retry_tasks.append(replace(current, attempt=current.attempt + 1))
                else:
                    results.append(failure)
                    progress_callback(failure)
            elif unfinished and not outcome["fatal_events"]:
                current = unfinished.pop(0)
                failure = self._process_failure_result(current, outcome)
                if current.attempt < self.config.retry_count:
                    retry_tasks.append(replace(current, attempt=current.attempt + 1))
                else:
                    results.append(failure)
                    progress_callback(failure)

            for task in reversed(retry_tasks + unfinished):
                pending.appendleft(task)

        return sorted(results, key=lambda result: result.sequence)

    def _run_chunk(self, chunk_number: int, tasks: Sequence[ConversionTask]):
        chunk_id = "chunk-{:04d}".format(chunk_number)
        chunk_directory = self.run_directory / chunk_id
        chunk_directory.mkdir(parents=True, exist_ok=False)
        events_path = chunk_directory / "events.jsonl"
        manifest_path = chunk_directory / "manifest.json"
        write_manifest(
            manifest_path,
            self.run_directory.name,
            chunk_id,
            {
                "acis_version": self.config.resolved_acis_version,
                "acis_units": self.config.acis.units,
                "heartbeat_interval_seconds": min(
                    5.0,
                    max(0.05, self.config.heartbeat_timeout_seconds / 3.0),
                ),
            },
            tasks,
            events_path,
        )
        specialized_worker = chunk_directory / self.worker_template.name
        specialized_worker.write_text(
            specialize_worker_template(
                self.worker_template.read_text(encoding="utf-8"),
                manifest_path,
            ),
            encoding="utf-8",
        )
        script_output = chunk_directory / "script_output.txt"
        command = self.command_factory(specialized_worker, script_output)
        stdout_path = chunk_directory / "process_stdout.txt"
        stderr_path = chunk_directory / "process_stderr.txt"
        timed_out = False
        last_activity = time.monotonic()
        observed_event_count = 0
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            process = subprocess.Popen(command, stdout=stdout_file, stderr=stderr_file)
            self.status_callback(
                {"kind": "process_started", "chunk_id": chunk_id, "pid": process.pid}
            )
            while process.poll() is None:
                try:
                    event_result = read_complete_events(events_path)
                except ProtocolError as error:
                    if not _is_transient_event_read_error(error):
                        _terminate_process(process)
                        raise
                    event_result = None
                if event_result is not None and len(event_result.events) > observed_event_count:
                    self._publish_event_updates(
                        event_result.events[observed_event_count:],
                        chunk_id,
                        process.pid,
                    )
                    observed_event_count = len(event_result.events)
                    last_activity = time.monotonic()
                if time.monotonic() - last_activity > self.config.heartbeat_timeout_seconds:
                    timed_out = True
                    _terminate_process(process)
                    break
                time.sleep(self.poll_interval_seconds)
            returncode = process.poll()
        try:
            event_result = read_complete_events(events_path)
        except ProtocolError as error:
            raise SupervisorError("event protocol failed in {}: {}".format(chunk_id, error)) from error
        fatal_events = [
            event for event in event_result.events if event.get("event") == "worker_fatal"
        ]
        if len(event_result.events) > observed_event_count:
            self._publish_event_updates(
                event_result.events[observed_event_count:],
                chunk_id,
                process.pid,
            )
        self.status_callback(
            {
                "kind": "process_finished",
                "chunk_id": chunk_id,
                "pid": process.pid,
                "returncode": returncode,
                "timed_out": timed_out,
            }
        )
        return {
            "chunk_id": chunk_id,
            "returncode": returncode,
            "timed_out": timed_out,
            "events": event_result.events,
            "fatal_events": fatal_events,
        }

    def _publish_event_updates(self, events, chunk_id, pid):
        for event in events:
            update = dict(event)
            update["kind"] = event["event"]
            update["chunk_id"] = chunk_id
            update["pid"] = pid
            self.status_callback(update)

    def _result_from_event(self, task, event, source_paths):
        status = Status(event["status"])
        output_size = int(event.get("output_size_bytes", 0))
        error_message = event.get("error_message", "")
        if status is Status.SUCCESS:
            try:
                output_size = self._finalize_output(task, event, source_paths)
            except Exception as error:
                status = Status.FAILED
                output_size = 0
                error_message = "output finalization failed: {}".format(error)
        return ConversionResult(
            sequence=task.sequence,
            task_id=task.task_id,
            source_name=task.source_path.name,
            source_path=str(task.source_path),
            output_name=task.output_path.name,
            output_path=str(task.output_path),
            output_format=task.output_format.value,
            source_size_bytes=task.source_size_bytes,
            output_size_bytes=output_size,
            start_time=event.get("start_time", ""),
            duration_seconds=float(event.get("duration_seconds", 0.0)),
            status=status,
            error_message=error_message,
            finish_time=event.get("finish_time", ""),
        )

    def _finalize_output(self, task, event, source_paths):
        assert_safe_output(task.output_path, self.config.output_dir, source_paths)
        staging = Path(event.get("staging_output_path", "")).resolve(strict=False)
        expected_staging = task.staging_output_path.resolve(strict=False)
        if os.path.normcase(str(staging)) != os.path.normcase(str(expected_staging)):
            raise ValueError("event staging path does not match the task")
        if staging.parent != task.output_path.parent.resolve(strict=False):
            raise ValueError("staging output is not beside the final output")
        if staging.suffix.lower() != task.output_path.suffix.lower():
            raise ValueError("staging extension differs from final output")
        if not staging.is_file() or staging.stat().st_size <= 0:
            raise ValueError("staging output is missing or empty")
        task.output_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, task.output_path)
        if not task.output_path.is_file() or task.output_path.stat().st_size <= 0:
            raise ValueError("final output is missing or empty")
        return task.output_path.stat().st_size

    def _process_failure_result(self, task, outcome):
        if outcome["timed_out"]:
            message = "worker timeout before terminal event"
        elif outcome["fatal_events"]:
            message = "worker fatal before terminal event: {}".format(
                outcome["fatal_events"][-1].get("error_message", "unknown error")
            )
        else:
            message = "worker process exited with code {} before terminal event".format(
                outcome["returncode"]
            )
        return ConversionResult(
            sequence=task.sequence,
            task_id=task.task_id,
            source_name=task.source_path.name,
            source_path=str(task.source_path),
            output_name=task.output_path.name,
            output_path=str(task.output_path),
            output_format=task.output_format.value,
            source_size_bytes=task.source_size_bytes,
            output_size_bytes=0,
            start_time="",
            duration_seconds=0.0,
            status=Status.FAILED,
            error_message=message,
        )
