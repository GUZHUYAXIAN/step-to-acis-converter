import json
from pathlib import Path
import tempfile
import unittest

from step_to_acis.models import ConversionTask, OutputFormat
from step_to_acis.protocol import (
    ProtocolError,
    append_event,
    load_manifest,
    read_complete_events,
    write_manifest,
)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source = self.root / "中文 输入" / "part 001.stp"
        self.output = self.root / "中文 输出" / "part 001.sab"
        self.staging = self.root / "中文 输出" / ".part.partial.sab"
        self.task = ConversionTask(
            sequence=1,
            task_id="task-1",
            source_path=self.source,
            output_path=self.output,
            staging_output_path=self.staging,
            output_format=OutputFormat.SAB,
            source_size_bytes=123,
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def event(self, event_name, **updates):
        value = {
            "schema_version": 1,
            "run_id": "run-1",
            "chunk_id": "chunk-1",
            "event": event_name,
            "timestamp_utc": "2026-08-11T10:00:00Z",
            "pid": 1234,
        }
        value.update(updates)
        return value

    def test_manifest_round_trips_unicode_paths_and_settings(self):
        path = self.root / "manifest.json"

        write_manifest(
            path,
            run_id="run-1",
            chunk_id="chunk-1",
            settings={"acis_version": "V22", "acis_units": "Millimeters"},
            tasks=[self.task],
            events_path=self.root / "事件 events.jsonl",
        )
        payload = load_manifest(path)

        self.assertEqual(1, payload["schema_version"])
        self.assertEqual(str(self.source), payload["tasks"][0]["source_path"])
        self.assertEqual(str(self.output), payload["tasks"][0]["output_path"])
        self.assertEqual("SAB", payload["tasks"][0]["output_format"])
        self.assertEqual("Millimeters", payload["settings"]["acis_units"])

    def test_manifest_rejects_wrong_schema(self):
        path = self.root / "manifest.json"
        path.write_text('{"schema_version": 99}', encoding="utf-8")

        with self.assertRaisesRegex(ProtocolError, "manifest schema"):
            load_manifest(path)

    def test_event_is_one_compact_json_object_per_line(self):
        path = self.root / "events.jsonl"

        append_event(path, self.event("worker_started"))
        append_event(path, self.event("worker_finished"))

        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(2, len(lines))
        self.assertTrue(all(line.startswith("{") and line.endswith("}") for line in lines))
        self.assertTrue(all("\n" not in line for line in lines))

    def test_required_event_names_are_accepted(self):
        path = self.root / "events.jsonl"
        events = [
            self.event("worker_started"),
            self.event("task_started", task_id="task-1"),
            self.event("heartbeat", task_id="task-1"),
            self.event("task_finished", task_id="task-1", status="Success"),
            self.event("worker_fatal", error_message="close failed"),
            self.event("worker_finished"),
        ]

        for event in events:
            append_event(path, event)

        self.assertEqual(6, len(path.read_text(encoding="utf-8").splitlines()))

    def test_invalid_event_status_and_missing_task_id_are_rejected(self):
        path = self.root / "events.jsonl"

        with self.assertRaisesRegex(ProtocolError, "event name"):
            append_event(path, self.event("unknown"))
        with self.assertRaisesRegex(ProtocolError, "task_id"):
            append_event(path, self.event("task_started"))
        with self.assertRaisesRegex(ProtocolError, "status"):
            append_event(
                path,
                self.event("task_finished", task_id="task-1", status="Maybe"),
            )

    def test_partial_final_line_is_ignored_and_preserved_for_diagnostics(self):
        path = self.root / "events.jsonl"
        valid = json.dumps(self.event("worker_started"), ensure_ascii=False)
        path.write_text(valid + "\n{\"schema_version\": 1", encoding="utf-8")

        result = read_complete_events(path)

        self.assertEqual(1, len(result.events))
        self.assertEqual('{"schema_version": 1', result.incomplete_tail)
        self.assertIn("unterminated final event", result.diagnostics[0])

    def test_malformed_complete_line_is_fatal(self):
        path = self.root / "events.jsonl"
        path.write_text("{bad}\n", encoding="utf-8")

        with self.assertRaisesRegex(ProtocolError, "line 1"):
            read_complete_events(path)

    def test_duplicate_terminal_events_are_rejected(self):
        path = self.root / "events.jsonl"
        first = json.dumps(
            self.event("task_finished", task_id="task-1", status="Success")
        )
        second = json.dumps(
            self.event("task_finished", task_id="task-1", status="Failed")
        )
        path.write_text(first + "\n" + second + "\n", encoding="utf-8")

        with self.assertRaisesRegex(ProtocolError, "duplicate terminal event"):
            read_complete_events(path)

    def test_terminal_event_flushes_and_calls_sync_hook(self):
        path = self.root / "events.jsonl"
        synced_descriptors = []

        append_event(
            path,
            self.event("task_finished", task_id="task-1", status="Success"),
            sync_hook=synced_descriptors.append,
        )

        self.assertEqual(1, len(synced_descriptors))
        self.assertGreater(path.stat().st_size, 0)
