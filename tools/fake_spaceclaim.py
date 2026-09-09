import json
import os
from pathlib import Path
import time


MANIFEST_PATH = None


def emit(path, manifest, event_name, task_id=None, **payload):
    event = {
        "schema_version": 1,
        "run_id": manifest["run_id"],
        "chunk_id": manifest["chunk_id"],
        "event": event_name,
        "timestamp_utc": "2026-08-11T10:00:00Z",
        "pid": os.getpid(),
    }
    if task_id is not None:
        event["task_id"] = task_id
    event.update(payload)
    with path.open("a", encoding="utf-8", newline="\n") as event_file:
        event_file.write(json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n")
        event_file.flush()


def task_result(task, status, output_size, error_message):
    return {
        "sequence": task["sequence"],
        "source_name": Path(task["source_path"]).name,
        "source_path": task["source_path"],
        "output_name": Path(task["output_path"]).name,
        "output_path": task["output_path"],
        "staging_output_path": task["staging_output_path"],
        "output_format": task["output_format"],
        "source_size_bytes": task["source_size_bytes"],
        "output_size_bytes": output_size,
        "start_time": "2026-08-11T10:00:00Z",
        "duration_seconds": 0.01,
        "status": status,
        "error_message": error_message,
        "finish_time": "2026-08-11T10:00:00Z",
    }


def main():
    manifest = json.loads(Path(MANIFEST_PATH).read_text(encoding="utf-8"))
    events = Path(manifest["events_path"])
    emit(events, manifest, "worker_started", task_count=len(manifest["tasks"]))
    completed = 0
    for task in manifest["tasks"]:
        task_id = task["task_id"]
        emit(
            events,
            manifest,
            "task_started",
            task_id=task_id,
            source_path=task["source_path"],
            output_path=task["output_path"],
            sequence=task["sequence"],
        )
        mode = Path(task["source_path"]).read_text(encoding="utf-8").split(":", 1)[1]
        if mode == "crash":
            os._exit(9)
        if mode == "hang":
            time.sleep(60)
        if mode == "failed" or (mode == "fail-once" and task.get("attempt", 0) == 0):
            emit(
                events,
                manifest,
                "task_finished",
                task_id=task_id,
                **task_result(task, "Failed", 0, "fake conversion failed")
            )
            completed += 1
            continue
        staging = Path(task["staging_output_path"])
        staging.parent.mkdir(parents=True, exist_ok=True)
        staging.write_bytes(b"FAKE-ACIS")
        emit(
            events,
            manifest,
            "task_finished",
            task_id=task_id,
            **task_result(task, "Success", staging.stat().st_size, "")
        )
        completed += 1
        if mode == "close-fatal":
            emit(
                events,
                manifest,
                "worker_fatal",
                task_id=task_id,
                error_message="fake close failed",
            )
            return 5
    emit(events, manifest, "worker_finished", completed_task_count=completed)
    return 0


raise SystemExit(main())
