import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import step_to_acis.probe_runner as probe_runner
from step_to_acis.probe_runner import (
    LaunchOutcome,
    ProbeStage,
    ProbeStageRecord,
    build_probe_stages,
    find_script_arg_exposure,
    launch_subprocess,
    profile_from_records,
    required_stages_passed,
    run_probe_stage,
    write_probe_report,
)
from step_to_acis.spaceclaim_command import SpaceClaimCommand


class ProbeRunnerTests(unittest.TestCase):
    def test_stages_isolate_required_and_optional_capabilities(self):
        stages = build_probe_stages(
            Path(r"C:\Program Files\ANSYS Inc\v222\SCDM\SpaceClaim.exe"),
            Path(r"E:\probe folder\probe.py"),
            Path(r"E:\probe folder\script-output.txt"),
        )

        self.assertEqual(
            ["required_base", "required_headless", "optional_script_output", "optional_script_args"],
            [stage.name for stage in stages],
        )
        self.assertEqual([True, True, False, False], [stage.required for stage in stages])
        self.assertFalse(stages[0].command.headless)
        self.assertTrue(stages[1].command.headless)
        self.assertIsNotNone(stages[2].command.script_output)
        self.assertEqual("中文 path with spaces", stages[3].command.script_args)

    def test_optional_failure_does_not_fail_required_profile(self):
        records = [
            ProbeStageRecord("required_base", True, True, "probe passed"),
            ProbeStageRecord("required_headless", True, True, "probe passed"),
            ProbeStageRecord("optional_script_args", False, False, "unsupported"),
        ]

        self.assertTrue(required_stages_passed(records))

    def test_required_failure_fails_profile(self):
        records = [
            ProbeStageRecord("required_base", True, True, "probe passed"),
            ProbeStageRecord("required_headless", True, False, "missing sentinel"),
        ]

        self.assertFalse(required_stages_passed(records))

    def test_script_args_exposure_prefers_exact_sys_argv_value(self):
        sentinel = {
            "sys_argv": ["probe.py", "中文 path with spaces"],
            "candidate_script_args": {"SomeArg": "中文 path with spaces"},
        }

        self.assertEqual(
            "sys.argv[1]",
            find_script_arg_exposure(sentinel, "中文 path with spaces"),
        )

    def test_script_args_exposure_can_use_a_named_global(self):
        sentinel = {
            "sys_argv": ["probe.py"],
            "candidate_script_args": {"ScriptArgs": "中文 path with spaces"},
        }

        self.assertEqual(
            "global:ScriptArgs",
            find_script_arg_exposure(sentinel, "中文 path with spaces"),
        )

    def test_script_args_exposure_is_none_when_value_did_not_arrive(self):
        sentinel = {"sys_argv": ["probe.py"], "candidate_script_args": {}}

        self.assertIsNone(
            find_script_arg_exposure(sentinel, "中文 path with spaces")
        )

    def test_stage_uses_fresh_sentinel_and_records_evidence(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            sentinel_path = root / "sentinel.json"
            sentinel_path.write_text("stale", encoding="utf-8")
            stage = ProbeStage(
                "required_headless",
                True,
                SpaceClaimCommand(Path("SpaceClaim.exe"), Path("probe.py")),
            )

            def launcher(command, timeout_seconds):
                self.assertFalse(sentinel_path.exists())
                self.assertEqual(120, timeout_seconds)
                sentinel_path.write_text(
                    json.dumps(
                        {
                            "probe_schema": 1,
                            "script_executed": True,
                            "api_expected": "V22",
                            "host_api_verified": True,
                            "sys_argv": [],
                            "candidate_script_args": {},
                            "globals_of_interest": [],
                            "unicode_round_trip": "中文 path with spaces",
                        }
                    ),
                    encoding="utf-8",
                )
                return LaunchOutcome(
                    returncode=0,
                    timed_out=False,
                    stdout="probe stdout",
                    stderr="",
                    started_at="2026-08-11T10:00:00+00:00",
                    ended_at="2026-08-11T10:00:01+00:00",
                    elapsed_seconds=1.0,
                )

            record = run_probe_stage(stage, sentinel_path, 120, launcher)

            self.assertTrue(record.passed)
            self.assertEqual(0, record.returncode)
            self.assertEqual("probe stdout", record.stdout)
            self.assertEqual("V22", record.sentinel["api_expected"])
            self.assertIn("/Headless=True", record.command)

    def test_script_args_stage_fails_when_value_is_not_exposed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            sentinel_path = root / "sentinel.json"
            stage = ProbeStage(
                "optional_script_args",
                False,
                SpaceClaimCommand(
                    Path("SpaceClaim.exe"),
                    Path("probe.py"),
                    script_args="中文 path with spaces",
                ),
            )

            def launcher(command, timeout_seconds):
                sentinel_path.write_text(
                    json.dumps(
                        {
                            "probe_schema": 1,
                            "script_executed": True,
                            "api_expected": "V22",
                            "host_api_verified": True,
                            "sys_argv": ["probe.py"],
                            "candidate_script_args": {},
                            "globals_of_interest": [],
                            "unicode_round_trip": "中文 path with spaces",
                        }
                    ),
                    encoding="utf-8",
                )
                return LaunchOutcome(0, False, "", "", "start", "end", 0.1)

            record = run_probe_stage(stage, sentinel_path, 120, launcher)

            self.assertFalse(record.passed)
            self.assertEqual("ScriptArgs value was not exposed to the script", record.reason)

    def test_real_launcher_captures_process_evidence(self):
        outcome = launch_subprocess(
            [sys.executable, "-c", "print('probe-ok')"],
            timeout_seconds=5,
        )

        self.assertEqual(0, outcome.returncode)
        self.assertFalse(outcome.timed_out)
        self.assertIn("probe-ok", outcome.stdout)
        self.assertTrue(outcome.started_at)
        self.assertTrue(outcome.ended_at)
        self.assertGreaterEqual(outcome.elapsed_seconds, 0)

    def test_launcher_disconnects_stdin_and_requests_no_console_on_windows(self):
        with patch.object(probe_runner.subprocess, "run") as run:
            run.return_value = SimpleNamespace(returncode=0, stdout=b"ok", stderr=b"")
            outcome = launch_subprocess(["SpaceClaim.exe"], 5)
        self.assertEqual(0, outcome.returncode)
        self.assertEqual(probe_runner.subprocess.DEVNULL, run.call_args.kwargs["stdin"])
        self.assertEqual(
            getattr(probe_runner.subprocess, "CREATE_NO_WINDOW", 0),
            run.call_args.kwargs["creationflags"],
        )

    def test_process_output_uses_preferred_encoding_without_locale_getencoding(self):
        legacy_locale = SimpleNamespace(
            getpreferredencoding=lambda do_setlocale=False: "utf-8"
        )

        with patch.object(probe_runner, "locale", legacy_locale):
            decoded = probe_runner._decode_process_output("中文".encode("utf-8"))

        self.assertEqual("中文", decoded)

    def test_real_launcher_classifies_timeout(self):
        outcome = launch_subprocess(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            timeout_seconds=0.05,
        )

        self.assertIsNone(outcome.returncode)
        self.assertTrue(outcome.timed_out)
        self.assertIn("timed out", outcome.stderr)

    def test_profile_records_optional_capabilities_and_fallback(self):
        records = [
            ProbeStageRecord("required_base", True, True, "probe passed"),
            ProbeStageRecord("required_headless", True, True, "probe passed"),
            ProbeStageRecord("optional_script_output", False, False, "unsupported"),
            ProbeStageRecord("optional_script_args", False, False, "unsupported"),
        ]

        profile = profile_from_records(records)

        self.assertTrue(profile.run_script)
        self.assertTrue(profile.script_api_v22)
        self.assertTrue(profile.exit_after_script)
        self.assertTrue(profile.headless)
        self.assertFalse(profile.script_output)
        self.assertFalse(profile.script_args)
        self.assertEqual("specialized_worker_literal", profile.script_args_strategy)

    def test_probe_report_preserves_commands_results_and_profile(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_path = Path(temporary_directory) / "probe_report.json"
            record = ProbeStageRecord(
                "required_base",
                True,
                True,
                "probe passed",
                command=("SpaceClaim.exe", "/RunScript=probe.py"),
                returncode=0,
                started_at="start",
                ended_at="end",
                elapsed_seconds=1.25,
                sentinel={"api_expected": "V22"},
            )
            profile = profile_from_records([record])

            write_probe_report(
                report_path,
                Path("SpaceClaim.exe"),
                [record],
                profile,
            )

            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(1, payload["probe_report_schema"])
            self.assertEqual(["SpaceClaim.exe", "/RunScript=probe.py"], payload["stages"][0]["command"])
            self.assertEqual(0, payload["stages"][0]["returncode"])
            self.assertTrue(payload["profile"]["run_script"])
