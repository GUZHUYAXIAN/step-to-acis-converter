import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from step_to_acis.cli import main, render_progress_bar
from step_to_acis.batch_service import CapabilityProfileError
from step_to_acis.models import ConversionResult, Status
from step_to_acis.probe_runner import CliCapabilityProfile


class CliSmokeTests(unittest.TestCase):
    def test_module_help_is_available(self):
        repo_root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(repo_root / "src")
        environment["PYTHONIOENCODING"] = "cp1252"

        result = subprocess.run(
            [sys.executable, "-m", "step_to_acis", "--help"],
            cwd=repo_root,
            env=environment,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("STEP", result.stdout)


class CliBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.input_dir = self.root / "input"
        self.output_dir = self.root / "output"
        self.input_dir.mkdir()
        self.executable = self.root / "SpaceClaim.exe"
        self.executable.write_bytes(b"fake")
        self.config_path = self.root / "config.json"

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

    def profile(self):
        return CliCapabilityProfile(
            run_script=True,
            script_api_v22=True,
            exit_after_script=True,
            headless=True,
            script_args=False,
            script_output=True,
            script_args_strategy="specialized_worker_literal",
        )

    def test_invalid_config_exits_two_before_supervisor_creation(self):
        self.write_config(spaceclaim_exe=str(self.root / "missing.exe"))
        output = io.StringIO()
        errors = io.StringIO()

        code = main(
            ["--config", str(self.config_path)],
            output_stream=output,
            error_stream=errors,
            supervisor_factory=lambda **kwargs: self.fail("supervisor was created"),
        )

        self.assertEqual(2, code)
        self.assertIn("spaceclaim_exe", errors.getvalue())

    def test_empty_input_writes_empty_reports_without_loading_spaceclaim_profile(self):
        self.write_config()
        output = io.StringIO()

        code = main(
            ["--config", str(self.config_path)],
            output_stream=output,
            capability_profile_loader=lambda *args: self.fail("profile was loaded"),
        )

        self.assertEqual(0, code)
        self.assertIn("总文件数：0", output.getvalue())
        csv_files = list(self.output_dir.glob("conversion_logs/*/conversion_log.csv"))
        self.assertEqual(1, len(csv_files))

    def test_partial_failures_complete_batch_with_warning_and_exit_zero(self):
        for name in ["a.stp", "b.step", "c.STP"]:
            (self.input_dir / name).write_bytes(b"STEP")
        self.write_config()
        output = io.StringIO()

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
                return results

        code = main(
            ["--config", str(self.config_path)],
            output_stream=output,
            capability_profile_loader=lambda *args: self.profile(),
            supervisor_factory=MixedSupervisor,
        )

        rendered = output.getvalue()
        self.assertEqual(0, code)
        self.assertIn("成功：1", rendered)
        self.assertIn("失败：1", rendered)
        self.assertIn("跳过：1", rendered)
        self.assertIn("存在 1 个转换失败文件", rendered)
        self.assertIn("当前：1 / 3", rendered)
        run_logs = list(self.output_dir.glob("conversion_logs/*/conversion_run.txt"))
        self.assertEqual(1, len(run_logs))
        run_log = run_logs[0].read_text(encoding="utf-8")
        self.assertIn("Process started: pid=1234 chunk=chunk-0001", run_log)
        self.assertIn("Process finished: pid=1234 chunk=chunk-0001 exit_code=0 timed_out=False", run_log)

    def test_capability_profile_error_keeps_distinct_exit_code_and_message(self):
        (self.input_dir / "a.stp").write_bytes(b"STEP")
        self.write_config()
        errors = io.StringIO()

        def reject_profile(*args):
            raise CapabilityProfileError("profile rejected")

        code = main(
            ["--config", str(self.config_path)],
            error_stream=errors,
            capability_profile_loader=reject_profile,
        )

        self.assertEqual(3, code)
        self.assertIn("SpaceClaim 能力档案无效", errors.getvalue())
        self.assertIn("profile rejected", errors.getvalue())

    def test_supervisor_exception_is_reported_as_batch_fatal(self):
        (self.input_dir / "a.stp").write_bytes(b"STEP")
        self.write_config()
        errors = io.StringIO()

        class ExplodingSupervisor:
            def __init__(inner_self, **kwargs):
                pass

            def run(inner_self, tasks, preflight, progress_callback):
                raise RuntimeError("supervisor exploded")

        code = main(
            ["--config", str(self.config_path)],
            error_stream=errors,
            capability_profile_loader=lambda *args: self.profile(),
            supervisor_factory=ExplodingSupervisor,
        )

        self.assertEqual(4, code)
        self.assertIn("批处理致命错误", errors.getvalue())
        self.assertIn("supervisor exploded", errors.getvalue())

    def test_progress_bar_has_stable_width_and_percentage(self):
        bar, percentage = render_progress_bar(5, 10, width=10)

        self.assertEqual("█████░░░░░", bar)
        self.assertEqual(50.0, percentage)
