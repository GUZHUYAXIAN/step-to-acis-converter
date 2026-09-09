from pathlib import Path
import json
import re
import tempfile
import unittest

from step_to_acis.probe_runner import LaunchOutcome, build_model_free_headless_stages
from step_to_acis.probe_service import run_model_free_probe
from step_to_acis.runtime_paths import RuntimePaths
from step_to_acis.spaceclaim_installations import SpaceClaimCandidate


class ProbeServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.executable = self.root / "v222" / "SCDM" / "SpaceClaim.exe"
        self.executable.parent.mkdir(parents=True)
        self.executable.write_bytes(b"fake executable")
        self.resources = Path(__file__).resolve().parents[1] / "spaceclaim"
        state = self.root / "state"
        self.paths = RuntimePaths(
            self.resources,
            state,
            state / "environment",
            state / "environment" / "capability_profiles",
            state / "environment" / "probe-runs",
            state / "gui_settings.json",
        )
        self.candidate = SpaceClaimCandidate(
            self.executable,
            "2022.2.0.0",
            "2022.2.1.2",
            "v222",
            (),
            "eligible",
            "eligible",
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_model_free_stages_are_all_headless(self):
        stages = build_model_free_headless_stages(
            self.executable, Path("probe.py"), Path("output.txt")
        )
        self.assertEqual(
            ["required_headless", "optional_script_output", "optional_script_args"],
            [stage.name for stage in stages],
        )
        self.assertTrue(all(stage.command.headless for stage in stages))

    def test_probe_template_contains_no_model_io_call_or_acis_path(self):
        source = (self.resources / "probe_v22.py").read_text(encoding="utf-8").casefold()
        for forbidden in (".stp", ".step", "documentopen.execute(", "documentsave.execute(", ".sab", ".sat"):
            self.assertNotIn(forbidden, source)

    def successful_launcher(self, command, timeout_seconds):
        script = Path(next(item.split("=", 1)[1] for item in command if item.startswith("/RunScript=")))
        match = re.search(r"^SENTINEL_PATH = u(.+)$", script.read_text(encoding="utf-8"), re.MULTILINE)
        sentinel = Path(json.loads(match.group(1)))
        sentinel.write_text(
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
        for item in command:
            if item.startswith("/ScriptOutput="):
                Path(item.split("=", 1)[1]).write_text("output", encoding="utf-8")
        return LaunchOutcome(0, False, "ok", "", "start", "end", 0.1)

    def test_pass_writes_report_and_authorizing_cache_without_model_files(self):
        outcome = run_model_free_probe(
            self.candidate, self.paths, launcher=self.successful_launcher
        )

        self.assertTrue(outcome.passed)
        self.assertTrue(outcome.report_path.is_file())
        self.assertTrue(outcome.profile_path.is_file())
        suffixes = {path.suffix.casefold() for path in self.paths.environment_root.rglob("*") if path.is_file()}
        self.assertTrue(suffixes.isdisjoint({".stp", ".step", ".sab", ".sat"}))

    def test_required_failure_and_timeout_never_write_authorizing_cache(self):
        outcomes = [
            LaunchOutcome(7, False, "", "failed", "start", "end", 0.1),
            LaunchOutcome(None, True, "", "timed out", "start", "end", 2.0),
        ]
        for launch_outcome in outcomes:
            with self.subTest(launch_outcome=launch_outcome):
                isolated = RuntimePaths(
                    self.resources,
                    self.root / str(launch_outcome.returncode),
                    self.root / str(launch_outcome.returncode) / "environment",
                    self.root / str(launch_outcome.returncode) / "environment" / "capability_profiles",
                    self.root / str(launch_outcome.returncode) / "environment" / "probe-runs",
                    self.root / str(launch_outcome.returncode) / "gui_settings.json",
                )
                outcome = run_model_free_probe(
                    self.candidate,
                    isolated,
                    launcher=lambda command, timeout: launch_outcome,
                )
                self.assertFalse(outcome.passed)
                self.assertTrue(outcome.report_path.is_file())
                self.assertIsNone(outcome.profile_path)
                self.assertEqual([], list(isolated.capability_profiles_root.glob("*.json")))


if __name__ == "__main__":
    unittest.main()
