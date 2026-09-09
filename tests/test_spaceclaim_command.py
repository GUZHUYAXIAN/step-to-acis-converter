import json
from pathlib import Path
import tempfile
import unittest

from step_to_acis.spaceclaim_command import (
    ProbeObservation,
    SpaceClaimCommand,
    build_command,
    evaluate_probe_execution,
    specialize_probe_template,
)
from step_to_acis.probe_runner import CliCapabilityProfile


class SpaceClaimCommandTests(unittest.TestCase):
    def test_required_options_are_individual_arguments(self):
        command = SpaceClaimCommand(
            executable=Path(r"C:\Program Files\ANSYS Inc\v222\SCDM\SpaceClaim.exe"),
            script=Path(r"E:\probe folder\probe_v22.py"),
        )

        actual = build_command(command)

        self.assertEqual(
            [
                r"C:\Program Files\ANSYS Inc\v222\SCDM\SpaceClaim.exe",
                r"/RunScript=E:\probe folder\probe_v22.py",
                "/ScriptAPI=V22",
                "/ExitAfterScript=True",
                "/Headless=True",
            ],
            actual,
        )

    def test_optional_values_remain_single_unquoted_arguments(self):
        command = SpaceClaimCommand(
            executable=Path(r"C:\Program Files\ANSYS Inc\v222\SCDM\SpaceClaim.exe"),
            script=Path(r"E:\probe folder\probe_v22.py"),
            script_args="中文 path with spaces",
            script_output=Path(r"E:\probe output\script output.txt"),
        )

        actual = build_command(command)

        self.assertIn("/ScriptArgs=中文 path with spaces", actual)
        self.assertIn(
            r"/ScriptOutput=E:\probe output\script output.txt",
            actual,
        )
        self.assertFalse(any('"' in argument for argument in actual))

    def test_production_command_rejects_an_unproven_required_capability(self):
        from step_to_acis.spaceclaim_command import build_production_command

        profile = CliCapabilityProfile(
            run_script=True,
            script_api_v22=True,
            exit_after_script=True,
            headless=False,
            script_args=False,
            script_output=True,
            script_args_strategy="specialized_worker_literal",
        )

        with self.assertRaisesRegex(ValueError, "Headless"):
            build_production_command(
                SpaceClaimCommand(Path("SpaceClaim.exe"), Path("worker.py")),
                profile,
            )

    def test_production_command_uses_specialized_worker_without_script_args(self):
        from step_to_acis.spaceclaim_command import build_production_command

        profile = CliCapabilityProfile(
            run_script=True,
            script_api_v22=True,
            exit_after_script=True,
            headless=True,
            script_args=False,
            script_output=True,
            script_args_strategy="specialized_worker_literal",
        )

        actual = build_production_command(
            SpaceClaimCommand(Path("SpaceClaim.exe"), Path("specialized-worker.py")),
            profile,
        )

        self.assertNotIn("/ScriptArgs", " ".join(actual))
        self.assertIn("/Headless=True", actual)

    def test_production_command_rejects_script_args_when_probe_failed(self):
        from step_to_acis.spaceclaim_command import build_production_command

        profile = CliCapabilityProfile(
            run_script=True,
            script_api_v22=True,
            exit_after_script=True,
            headless=True,
            script_args=False,
            script_output=True,
            script_args_strategy="specialized_worker_literal",
        )

        with self.assertRaisesRegex(ValueError, "ScriptArgs"):
            build_production_command(
                SpaceClaimCommand(
                    Path("SpaceClaim.exe"),
                    Path("worker.py"),
                    script_args="manifest.json",
                ),
                profile,
            )


class ProbeEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_sentinel(self, value=None):
        payload = value or {
            "probe_schema": 1,
            "script_executed": True,
            "api_expected": "V22",
            "sys_argv": [],
            "candidate_script_args": {},
            "globals_of_interest": [],
            "unicode_round_trip": "中文 path with spaces",
            "host_api_verified": True,
        }
        path = self.root / "sentinel.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_specialization_replaces_only_the_sentinel_constant(self):
        template = "SENTINEL_PATH = None\nprint('SENTINEL_PATH = None')\n"

        actual = specialize_probe_template(
            template,
            self.root / "中文 folder" / "sentinel.json",
        )

        self.assertIn(
            'SENTINEL_PATH = u"{}"'.format(
                str(self.root / "中文 folder" / "sentinel.json")
                .replace("\\", "\\\\")
                .replace("中文", "\\u4e2d\\u6587")
            ),
            actual,
        )
        self.assertIn("print('SENTINEL_PATH = None')", actual)

    def test_nonzero_exit_is_rejected_even_with_sentinel(self):
        sentinel = self.write_sentinel()

        evaluation = evaluate_probe_execution(
            ProbeObservation(returncode=7, timed_out=False, sentinel_path=sentinel)
        )

        self.assertFalse(evaluation.passed)
        self.assertIn("exit code 7", evaluation.reason)

    def test_timeout_is_rejected(self):
        evaluation = evaluate_probe_execution(
            ProbeObservation(
                returncode=None,
                timed_out=True,
                sentinel_path=self.root / "missing.json",
            )
        )

        self.assertFalse(evaluation.passed)
        self.assertEqual("process timed out", evaluation.reason)

    def test_missing_and_malformed_sentinels_are_rejected(self):
        missing = evaluate_probe_execution(
            ProbeObservation(
                returncode=0,
                timed_out=False,
                sentinel_path=self.root / "missing.json",
            )
        )
        malformed_path = self.root / "malformed.json"
        malformed_path.write_text("{", encoding="utf-8")
        malformed = evaluate_probe_execution(
            ProbeObservation(
                returncode=0,
                timed_out=False,
                sentinel_path=malformed_path,
            )
        )

        self.assertEqual("sentinel file is missing", missing.reason)
        self.assertEqual("sentinel JSON is invalid", malformed.reason)

    def test_required_script_output_must_be_nonempty(self):
        sentinel = self.write_sentinel()
        output = self.root / "script-output.txt"
        output.write_bytes(b"")

        evaluation = evaluate_probe_execution(
            ProbeObservation(
                returncode=0,
                timed_out=False,
                sentinel_path=sentinel,
                script_output_path=output,
                require_script_output=True,
            )
        )

        self.assertFalse(evaluation.passed)
        self.assertEqual("script output is missing or empty", evaluation.reason)

    def test_valid_sentinel_passes(self):
        sentinel = self.write_sentinel()

        evaluation = evaluate_probe_execution(
            ProbeObservation(returncode=0, timed_out=False, sentinel_path=sentinel)
        )

        self.assertTrue(evaluation.passed)
        self.assertEqual("probe passed", evaluation.reason)
        self.assertEqual("V22", evaluation.sentinel["api_expected"])

    def test_sentinel_without_v22_symbols_is_rejected(self):
        sentinel = self.write_sentinel(
            {
                "probe_schema": 1,
                "script_executed": True,
                "api_expected": "V22",
                "sys_argv": [],
                "candidate_script_args": {},
                "globals_of_interest": [],
                "unicode_round_trip": "中文 path with spaces",
                "host_api_verified": False,
            }
        )

        evaluation = evaluate_probe_execution(
            ProbeObservation(returncode=0, timed_out=False, sentinel_path=sentinel)
        )

        self.assertFalse(evaluation.passed)
        self.assertEqual("sentinel content is invalid", evaluation.reason)
