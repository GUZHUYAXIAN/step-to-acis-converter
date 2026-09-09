import json
from pathlib import Path
import tempfile
import unittest

from tools.fake_spaceclaim_host import (
    FakeHostError,
    extract_specialized_path,
    parse_arguments,
    run_script,
)


class FakeSpaceClaimHostTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_command_parser_accepts_required_headless_v22_options_and_chinese_path(self):
        script = self.root / "中文 空格" / "probe.py"
        output = self.root / "输出 记录.txt"
        parsed = parse_arguments(
            [
                "/RunScript={}".format(script),
                "/ScriptAPI=V22",
                "/ExitAfterScript=True",
                "/Headless=True",
                "/ScriptOutput={}".format(output),
            ]
        )

        self.assertEqual(script, parsed.script)
        self.assertEqual(output, parsed.script_output)

    def test_probe_writes_valid_model_free_sentinel_and_script_output(self):
        sentinel = self.root / "状态" / "sentinel.json"
        script_output = self.root / "output.txt"
        script = self.root / "probe.py"
        script.write_text(
            'SENTINEL_PATH = u{}\n'.format(json.dumps(str(sentinel), ensure_ascii=True)),
            encoding="utf-8",
        )

        result = run_script(script, script_output)

        payload = json.loads(sentinel.read_text(encoding="utf-8"))
        self.assertEqual(0, result)
        self.assertTrue(payload["script_executed"])
        self.assertTrue(payload["host_api_verified"])
        self.assertEqual("V22", payload["api_expected"])
        self.assertTrue(script_output.is_file())
        self.assertFalse(any(path.suffix.casefold() in {".stp", ".step", ".sab", ".sat"} for path in self.root.rglob("*")))

    def test_worker_emits_success_failed_success_and_writes_only_fake_staging_bytes(self):
        input_root = self.root / "合成 输入"
        output_root = self.root / "隔离 输出"
        input_root.mkdir()
        modes = ("success", "failed", "success")
        tasks = []
        source_bytes = {}
        for index, mode in enumerate(modes, start=1):
            source = input_root / "fixture {}.txt".format(index)
            source.write_text("MODE:{}".format(mode), encoding="utf-8")
            source_bytes[source] = source.read_bytes()
            tasks.append(
                {
                    "sequence": index,
                    "task_id": "task-{}".format(index),
                    "source_path": str(source),
                    "output_path": str(output_root / "fixture {}.sab".format(index)),
                    "staging_output_path": str(output_root / ".fixture {}.partial.sab".format(index)),
                    "output_format": "SAB",
                    "source_size_bytes": source.stat().st_size,
                    "attempt": 0,
                }
            )
        events = self.root / "events.jsonl"
        manifest = self.root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": "run-1",
                    "chunk_id": "chunk-1",
                    "settings": {},
                    "tasks": tasks,
                    "events_path": str(events),
                }
            ),
            encoding="utf-8",
        )
        script = self.root / "worker.py"
        script.write_text(
            'MANIFEST_PATH = u{}\n'.format(json.dumps(str(manifest), ensure_ascii=True)),
            encoding="utf-8",
        )

        result = run_script(script, None)

        records = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
        finished = [event for event in records if event["event"] == "task_finished"]
        self.assertEqual(0, result)
        self.assertEqual(["Success", "Failed", "Success"], [event["status"] for event in finished])
        self.assertEqual(source_bytes, {path: path.read_bytes() for path in source_bytes})
        self.assertEqual(2, len(list(output_root.glob("*.partial.sab"))))
        self.assertTrue(all(path.read_bytes() == b"FAKE-ACIS-VALIDATION" for path in output_root.glob("*.partial.sab")))

    def test_script_requires_exactly_one_supported_marker(self):
        with self.assertRaises(FakeHostError):
            extract_specialized_path("print('no marker')", "SENTINEL_PATH")
        with self.assertRaises(FakeHostError):
            extract_specialized_path(
                'SENTINEL_PATH = u"one"\nSENTINEL_PATH = u"two"\n',
                "SENTINEL_PATH",
            )
        script = self.root / "unknown.py"
        script.write_text("print('unknown')", encoding="utf-8")
        with self.assertRaises(FakeHostError):
            run_script(script, None)


if __name__ == "__main__":
    unittest.main()
