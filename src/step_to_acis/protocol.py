from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .models import ConversionTask, Status


MANIFEST_SCHEMA_VERSION = 1
EVENT_SCHEMA_VERSION = 1
EVENT_NAMES = frozenset(
    [
        "worker_started",
        "task_started",
        "heartbeat",
        "task_finished",
        "worker_fatal",
        "worker_finished",
    ]
)
TASK_EVENTS = frozenset(["task_started", "task_finished"])
TERMINAL_EVENTS = frozenset(["task_finished"])


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class EventReadResult:
    events: tuple[dict[str, Any], ...]
    incomplete_tail: str
    diagnostics: tuple[str, ...]


def write_manifest(
    path: Path,
    run_id: str,
    chunk_id: str,
    settings: Mapping[str, Any],
    tasks: Iterable[ConversionTask],
    events_path: Path,
) -> None:
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "chunk_id": chunk_id,
        "settings": dict(settings),
        "tasks": [_task_record(task) for task in tasks],
        "events_path": str(events_path),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary_path, path)


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProtocolError("manifest JSON is invalid: {}".format(error)) from error
    if not isinstance(payload, dict) or payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ProtocolError("manifest schema is not supported")
    required = ("run_id", "chunk_id", "settings", "tasks", "events_path")
    missing = [name for name in required if name not in payload]
    if missing:
        raise ProtocolError("manifest is missing field: {}".format(missing[0]))
    if not isinstance(payload["tasks"], list):
        raise ProtocolError("manifest tasks must be a list")
    return payload


def append_event(
    path: Path,
    event: Mapping[str, Any],
    sync_hook: Callable[[int], Any] | None = None,
) -> None:
    normalized = dict(event)
    _validate_event(normalized)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(normalized, ensure_ascii=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8", newline="\n") as event_file:
        event_file.write(line + "\n")
        event_file.flush()
        if normalized["event"] in TERMINAL_EVENTS:
            (sync_hook or os.fsync)(event_file.fileno())


def read_complete_events(path: Path) -> EventReadResult:
    if not path.exists():
        return EventReadResult((), "", ())
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ProtocolError("cannot read events: {}".format(error)) from error
    diagnostics = []
    incomplete_tail = ""
    if content and not content.endswith("\n"):
        complete_content, separator, incomplete_tail = content.rpartition("\n")
        if not separator:
            complete_content = ""
            incomplete_tail = content
        diagnostics.append("unterminated final event was ignored")
    else:
        complete_content = content

    events = []
    terminal_task_ids = set()
    for line_number, line in enumerate(complete_content.splitlines(), start=1):
        if not line:
            raise ProtocolError("event line {} is empty".format(line_number))
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise ProtocolError("event line {} is invalid JSON".format(line_number)) from error
        try:
            _validate_event(event)
        except ProtocolError as error:
            raise ProtocolError("event line {}: {}".format(line_number, error)) from error
        if event["event"] in TERMINAL_EVENTS:
            task_id = event["task_id"]
            if task_id in terminal_task_ids:
                raise ProtocolError(
                    "duplicate terminal event for task_id {}".format(task_id)
                )
            terminal_task_ids.add(task_id)
        events.append(event)
    return EventReadResult(tuple(events), incomplete_tail, tuple(diagnostics))


def _task_record(task: ConversionTask) -> dict[str, Any]:
    return {
        "sequence": task.sequence,
        "task_id": task.task_id,
        "source_path": str(task.source_path),
        "output_path": str(task.output_path),
        "staging_output_path": str(task.staging_output_path),
        "output_format": task.output_format.value,
        "source_size_bytes": task.source_size_bytes,
        "attempt": task.attempt,
        "requires_spaceclaim_path_probe": task.requires_spaceclaim_path_probe,
    }


def _validate_event(event: Any) -> None:
    if not isinstance(event, dict):
        raise ProtocolError("event must be a JSON object")
    if event.get("schema_version") != EVENT_SCHEMA_VERSION:
        raise ProtocolError("event schema is not supported")
    event_name = event.get("event")
    if event_name not in EVENT_NAMES:
        raise ProtocolError("event name is invalid")
    for field in ("run_id", "chunk_id", "timestamp_utc", "pid"):
        if field not in event:
            raise ProtocolError("event is missing field: {}".format(field))
    if event_name in TASK_EVENTS and not event.get("task_id"):
        raise ProtocolError("task_id is required for {}".format(event_name))
    if event_name == "task_finished":
        valid_statuses = {status.value for status in Status}
        if event.get("status") not in valid_statuses:
            raise ProtocolError("status is invalid")
