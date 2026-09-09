# Python Script, API Version = V22
from __future__ import print_function

import io
import json
import os
import threading
import time
import traceback

from SpaceClaim.Api.V22 import AcisUnits, AcisVersion, ExportOptions, Window
from SpaceClaim.Api.V22.Scripting.Commands import DocumentOpen, DocumentSave


MANIFEST_PATH = None
EVENT_SCHEMA_VERSION = 1


try:
    text_type = unicode
except NameError:
    text_type = str


def utc_now():
    now = time.time()
    base = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now))
    milliseconds = int((now - int(now)) * 1000)
    return "{}.{:03d}Z".format(base, milliseconds)


def error_text(error):
    try:
        return text_type(error)
    except Exception:
        return repr(error)


class EventWriter(object):
    def __init__(self, path, run_id, chunk_id):
        self.path = path
        self.run_id = run_id
        self.chunk_id = chunk_id
        self.lock = threading.RLock()

    def emit(self, event_name, task_id=None, **payload):
        event = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "run_id": self.run_id,
            "chunk_id": self.chunk_id,
            "event": event_name,
            "timestamp_utc": utc_now(),
            "pid": os.getpid(),
        }
        if task_id is not None:
            event["task_id"] = task_id
        event.update(payload)
        serialized = json.dumps(event, ensure_ascii=True, separators=(",", ":"))
        with self.lock:
            with io.open(self.path, "a", encoding="utf-8") as event_file:
                event_file.write(text_type(serialized) + u"\n")
                event_file.flush()
                if event_name == "task_finished":
                    sync = getattr(os, "fsync", None)
                    if sync is not None:
                        sync(event_file.fileno())


class Heartbeat(object):
    def __init__(self, writer, interval_seconds):
        self.writer = writer
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self.state_lock = threading.RLock()
        self.task_id = None
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True

    def start(self):
        self.thread.start()

    def set_task(self, task_id):
        with self.state_lock:
            self.task_id = task_id

    def stop(self):
        self.stop_event.set()
        self.thread.join(1.0)

    def _run(self):
        while not self.stop_event.wait(self.interval_seconds):
            with self.state_lock:
                task_id = self.task_id
            self.writer.emit("heartbeat", task_id=task_id)


def load_manifest(path):
    if not path:
        raise RuntimeError("MANIFEST_PATH was not specialized")
    with io.open(path, "r", encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    if manifest.get("schema_version") != 1:
        raise RuntimeError("unsupported manifest schema")
    return manifest


def create_export_options(settings):
    options = ExportOptions.Create()
    version_name = settings.get("acis_version", "V22")
    units_name = settings.get("acis_units", "Millimeters")
    options.Acis.Version = getattr(AcisVersion, version_name)
    options.Acis.Units = getattr(AcisUnits, units_name)
    return options


def validate_output(path):
    if not os.path.isfile(path):
        raise RuntimeError("output is missing or empty")
    size = os.path.getsize(path)
    if size <= 0:
        raise RuntimeError("output is missing or empty")
    return size


def close_active_document():
    active_window = Window.ActiveWindow
    if active_window is None:
        raise RuntimeError("active SpaceClaim window is missing during close")
    active_window.Close()


def result_payload(task, start_time, started_counter, status, output_size, message):
    return {
        "sequence": task["sequence"],
        "source_name": os.path.basename(task["source_path"]),
        "source_path": task["source_path"],
        "output_name": os.path.basename(task["output_path"]),
        "output_path": task["output_path"],
        "staging_output_path": task["staging_output_path"],
        "output_format": task["output_format"],
        "source_size_bytes": os.path.getsize(task["source_path"]),
        "output_size_bytes": output_size,
        "start_time": start_time,
        "duration_seconds": time.time() - started_counter,
        "status": status,
        "error_message": message,
        "finish_time": utc_now(),
    }


def run_task(task, settings, writer, heartbeat):
    task_id = task["task_id"]
    source_path = task["source_path"]
    staging_path = task["staging_output_path"]
    start_time = utc_now()
    started_counter = time.time()
    opened = False
    writer.emit(
        "task_started",
        task_id=task_id,
        sequence=task["sequence"],
        source_path=source_path,
        output_path=task["output_path"],
    )
    heartbeat.set_task(task_id)
    status = "Failed"
    output_size = 0
    message = ""
    try:
        if os.path.isfile(staging_path):
            os.remove(staging_path)
        options = create_export_options(settings)
        DocumentOpen.Execute(source_path)
        opened = True
        DocumentSave.Execute(staging_path, options)
        output_size = validate_output(staging_path)
        status = "Success"
    except Exception as error:
        message = error_text(error)

    close_error = None
    close_traceback = ""
    heartbeat.set_task(None)
    if opened:
        try:
            close_active_document()
        except Exception as error:
            close_error = error
            close_traceback = traceback.format_exc()

    writer.emit(
        "task_finished",
        task_id=task_id,
        **result_payload(
            task,
            start_time,
            started_counter,
            status,
            output_size,
            message,
        )
    )
    if close_error is not None:
        writer.emit(
            "worker_fatal",
            task_id=task_id,
            error_message="document close failed: {}".format(
                error_text(close_error)
            ),
            traceback=close_traceback,
        )
        return False
    return True


def main():
    manifest = load_manifest(MANIFEST_PATH)
    writer = EventWriter(
        manifest["events_path"],
        manifest["run_id"],
        manifest["chunk_id"],
    )
    settings = manifest["settings"]
    heartbeat = Heartbeat(
        writer,
        float(settings.get("heartbeat_interval_seconds", 5.0)),
    )
    writer.emit("worker_started", task_count=len(manifest["tasks"]))
    heartbeat.start()
    try:
        for task in manifest["tasks"]:
            if not run_task(task, settings, writer, heartbeat):
                return 5
        writer.emit("worker_finished", completed_task_count=len(manifest["tasks"]))
        return 0
    except Exception as error:
        writer.emit(
            "worker_fatal",
            error_message=error_text(error),
            traceback=traceback.format_exc(),
        )
        return 5
    finally:
        heartbeat.stop()


WORKER_EXIT_CODE = main()
