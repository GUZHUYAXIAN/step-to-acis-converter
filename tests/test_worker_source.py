import ast
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
import warnings

from step_to_acis.models import ConversionTask, OutputFormat
from step_to_acis.protocol import read_complete_events, write_manifest
from step_to_acis.spaceclaim_command import specialize_worker_template


class FakeSpaceClaimRuntime:
    def __init__(self):
        self.current_source = None
        self.opened = []
        self.saved = []
        self.closed = 0
        self.options = []
        self.open_failures = set()
        self.save_failures = set()
        self.zero_outputs = set()
        self.missing_outputs = set()
        self.close_fails = False
        self.previous_modules = {}

    def install(self):
        runtime = self

        class AcisVersion:
            V22 = "ENUM-V22"

        class AcisUnits:
            Millimeters = "ENUM-MM"

        class ExportOptions:
            @staticmethod
            def Create():
                options = types.SimpleNamespace(
                    Acis=types.SimpleNamespace(Version=None, Units=None)
                )
                runtime.options.append(options)
                return options

        class DocumentOpen:
            @staticmethod
            def Execute(source_path):
                runtime.current_source = str(source_path)
                runtime.opened.append(str(source_path))
                if Path(source_path).name in runtime.open_failures:
                    raise RuntimeError("open failed")

        class DocumentSave:
            @staticmethod
            def Execute(output_path, options):
                source_name = Path(runtime.current_source).name
                runtime.saved.append((str(output_path), options))
                if source_name in runtime.save_failures:
                    raise RuntimeError("save failed")
                output = Path(output_path)
                output.parent.mkdir(parents=True, exist_ok=True)
                if source_name in runtime.missing_outputs:
                    return
                if source_name in runtime.zero_outputs:
                    output.write_bytes(b"")
                else:
                    output.write_bytes(b"ACIS-BINARY")

        class ActiveWindow:
            def Close(self):
                runtime.closed += 1
                if runtime.close_fails:
                    raise RuntimeError("close failed")

        Window = type("Window", (), {"ActiveWindow": ActiveWindow()})

        spaceclaim = types.ModuleType("SpaceClaim")
        api = types.ModuleType("SpaceClaim.Api")
        v22 = types.ModuleType("SpaceClaim.Api.V22")
        scripting = types.ModuleType("SpaceClaim.Api.V22.Scripting")
        commands = types.ModuleType("SpaceClaim.Api.V22.Scripting.Commands")
        v22.AcisVersion = AcisVersion
        v22.AcisUnits = AcisUnits
        v22.ExportOptions = ExportOptions
        v22.Window = Window
        commands.DocumentOpen = DocumentOpen
        commands.DocumentSave = DocumentSave
        modules = {
            "SpaceClaim": spaceclaim,
            "SpaceClaim.Api": api,
            "SpaceClaim.Api.V22": v22,
            "SpaceClaim.Api.V22.Scripting": scripting,
            "SpaceClaim.Api.V22.Scripting.Commands": commands,
        }
        for name, module in modules.items():
            self.previous_modules[name] = sys.modules.get(name)
            sys.modules[name] = module

    def uninstall(self):
        for name, previous in self.previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.output_dir = self.root / "输出 folder"
        self.output_dir.mkdir()
        self.events_path = self.root / "events.jsonl"
        self.manifest_path = self.root / "manifest.json"
        self.runtime = FakeSpaceClaimRuntime()
        self.runtime.install()

    def tearDown(self):
        self.runtime.uninstall()
        self.temporary_directory.cleanup()

    def task(self, sequence, name, output_format=OutputFormat.SAB):
        source = self.root / "输入 folder" / name
        source.parent.mkdir(exist_ok=True)
        source.write_bytes(b"STEP-DATA")
        output = self.output_dir / (source.stem + output_format.extension)
        staging = self.output_dir / ("." + source.stem + ".partial" + output_format.extension)
        return ConversionTask(
            sequence=sequence,
            task_id="task-{}".format(sequence),
            source_path=source,
            output_path=output,
            staging_output_path=staging,
            output_format=output_format,
            source_size_bytes=source.stat().st_size,
        )

    def run_worker(self, tasks, settings=None):
        write_manifest(
            self.manifest_path,
            "run-1",
            "chunk-1",
            settings
            or {
                "acis_version": "V22",
                "acis_units": "Millimeters",
                "heartbeat_interval_seconds": 60,
            },
            tasks,
            self.events_path,
        )
        repository_root = Path(__file__).resolve().parents[1]
        template = repository_root / "spaceclaim" / "worker_v22.py"
        specialized = self.root / "worker specialized.py"
        specialized.write_text(
            specialize_worker_template(
                template.read_text(encoding="utf-8"),
                self.manifest_path,
            ),
            encoding="utf-8",
        )
        namespace = runpy.run_path(str(specialized), run_name="__main__")
        return namespace["WORKER_EXIT_CODE"], read_complete_events(self.events_path).events

    def test_worker_source_avoids_python3_only_syntax(self):
        repository_root = Path(__file__).resolve().parents[1]
        source = (repository_root / "spaceclaim" / "worker_v22.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)

        forbidden = (ast.AnnAssign, ast.JoinedStr, ast.AsyncFunctionDef, ast.Await)
        self.assertEqual([], [type(node).__name__ for node in ast.walk(tree) if isinstance(node, forbidden)])

    def test_worker_emits_no_python_deprecation_warnings(self):
        task = self.task(1, "part.stp")

        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            self.run_worker([task])

        self.assertEqual([], [str(item.message) for item in captured])

    def test_worker_uses_flush_and_close_when_os_fsync_is_unavailable(self):
        task = self.task(1, "part.stp")
        original_fsync = os.fsync
        del os.fsync
        try:
            exit_code, events = self.run_worker([task])
        finally:
            os.fsync = original_fsync

        terminal = [event for event in events if event["event"] == "task_finished"]
        self.assertEqual(0, exit_code)
        self.assertEqual(1, len(terminal))
        self.assertEqual("Success", terminal[0]["status"])

    def test_successful_sab_sets_explicit_v22_options_and_closes_document(self):
        task = self.task(1, "连接板 001.stp")

        exit_code, events = self.run_worker([task])

        terminal = [event for event in events if event["event"] == "task_finished"]
        self.assertEqual(0, exit_code)
        self.assertEqual("Success", terminal[0]["status"])
        self.assertGreater(terminal[0]["output_size_bytes"], 0)
        self.assertEqual("ENUM-V22", self.runtime.options[0].Acis.Version)
        self.assertEqual("ENUM-MM", self.runtime.options[0].Acis.Units)
        self.assertEqual(1, self.runtime.closed)
        self.assertTrue(task.staging_output_path.is_file())

    def test_sat_uses_sat_staging_extension(self):
        task = self.task(1, "part.step", OutputFormat.SAT)

        _, events = self.run_worker([task])

        terminal = [event for event in events if event["event"] == "task_finished"][0]
        self.assertEqual("Success", terminal["status"])
        self.assertTrue(self.runtime.saved[0][0].endswith(".sat"))

    def test_open_failure_does_not_stop_the_next_task(self):
        failed = self.task(1, "bad-open.stp")
        succeeded = self.task(2, "good.step")
        self.runtime.open_failures.add("bad-open.stp")

        exit_code, events = self.run_worker([failed, succeeded])

        terminal = [event for event in events if event["event"] == "task_finished"]
        self.assertEqual(0, exit_code)
        self.assertEqual(["Failed", "Success"], [event["status"] for event in terminal])
        self.assertIn("open failed", terminal[0]["error_message"])

    def test_missing_or_zero_output_is_failed(self):
        missing = self.task(1, "missing.stp")
        zero = self.task(2, "zero.step")
        self.runtime.missing_outputs.add("missing.stp")
        self.runtime.zero_outputs.add("zero.step")

        _, events = self.run_worker([missing, zero])

        terminal = [event for event in events if event["event"] == "task_finished"]
        self.assertEqual(["Failed", "Failed"], [event["status"] for event in terminal])
        self.assertTrue(all("empty" in event["error_message"] for event in terminal))

    def test_close_failure_emits_worker_fatal_and_stops_chunk(self):
        first = self.task(1, "first.stp")
        second = self.task(2, "second.stp")
        self.runtime.close_fails = True

        exit_code, events = self.run_worker([first, second])

        self.assertNotEqual(0, exit_code)
        self.assertEqual(1, len([event for event in events if event["event"] == "task_started"]))
        fatals = [event for event in events if event["event"] == "worker_fatal"]
        self.assertEqual(1, len(fatals))
        self.assertIn("close failed", fatals[0]["error_message"])
