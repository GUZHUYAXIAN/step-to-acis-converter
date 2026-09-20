from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from step_to_acis.capability_cache import CachedCapability, ExecutableIdentity
from step_to_acis.environment_controller import EnvironmentController, _resources_exist
from step_to_acis.probe_runner import CliCapabilityProfile
from step_to_acis.probe_service import ProbeServiceOutcome
from step_to_acis.runtime_paths import RuntimePaths
from step_to_acis.spaceclaim_installations import SpaceClaimCandidate


class EnvironmentControllerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        resource_root = self.root / "resources"
        resource_root.mkdir()
        for name in ("probe_v22.py", "worker_v22.py", "probe_v261.py", "worker_v261.py"):
            (resource_root / name).write_text("resource", encoding="utf-8")
        state_root = self.root / "state"
        self.paths = RuntimePaths(
            resource_root,
            state_root,
            state_root / "environment",
            state_root / "environment" / "capability_profiles",
            state_root / "environment" / "probe-runs",
            state_root / "gui_settings.json",
        )
        self.executable = self.root / "v222" / "SCDM" / "SpaceClaim.exe"
        self.executable.parent.mkdir(parents=True)
        self.executable.write_bytes(b"exe")
        self.eligible = SpaceClaimCandidate(
            self.executable,
            "2022.2.0.0",
            "2022.2.1.0",
            "v222",
            ("fixed_drive",),
            "eligible",
            "eligible",
        )
        self.unsupported = replace(
            self.eligible,
            executable=self.root / "v241" / "SCDM" / "SpaceClaim.exe",
            product_version="2024.1.0.0",
            file_version="2024.1.0.0",
            layout_version="v241",
            eligibility="unsupported",
            reason="only v222 is verified",
        )
        self.identity = ExecutableIdentity(
            str(self.executable.resolve()),
            "A" * 64,
            self.eligible.product_version,
            self.eligible.file_version,
        )
        self.profile = CliCapabilityProfile(
            True, True, True, True, False, True, "specialized_worker_literal"
        )
        self.report = self.paths.probe_runs_root / "run" / "probe-report.json"
        self.cache = CachedCapability(
            self.identity, self.profile, True, str(self.report), "now"
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def make_controller(
        self,
        *,
        candidates=(),
        cache=None,
        probe_outcome=None,
        classify=None,
        identity_error=None,
        previous=None,
    ):
        calls = {"discover": 0, "probe": 0, "save": 0}

        def discover(previous_path):
            calls["discover"] += 1
            return tuple(candidates)

        def identity(candidate):
            if identity_error is not None:
                raise identity_error
            return self.identity

        def probe(candidate, paths):
            calls["probe"] += 1
            return probe_outcome or ProbeServiceOutcome(
                True,
                paths.capability_profiles_root / "profile.json",
                self.report,
                "probe passed",
                False,
            )

        controller = EnvironmentController(
            self.paths,
            windows_x64_probe=lambda: True,
            resource_probe=lambda paths: True,
            temp_writable_probe=lambda path: True,
            state_writable_probe=lambda path: True,
            discoverer=discover,
            manual_classifier=classify or (lambda path: self.eligible),
            identity_builder=identity,
            cache_loader=lambda path, current: cache,
            probe_service=probe,
            previous_loader=lambda path: previous,
            selected_saver=lambda path, value: calls.__setitem__(
                "save", calls["save"] + 1
            ),
        )
        return controller, calls

    def test_scan_selects_first_eligible_and_runs_probe_when_cache_missing(self):
        controller, calls = self.make_controller(
            candidates=(self.unsupported, self.eligible)
        )

        state = controller.scan()

        self.assertEqual(self.eligible, state.selected)
        self.assertTrue(state.can_enter_converter)
        self.assertEqual(1, calls["probe"])
        self.assertEqual(1, calls["save"])
        self.assertTrue(any(check.status == "warning" for check in state.checks))

    def test_scan_reports_stages_and_cache_hit_does_not_claim_live_probe(self):
        controller, calls = self.make_controller(candidates=(self.eligible,), cache=self.cache)
        progress = []
        controller.set_progress_callback(progress.append)
        state = controller.scan()
        self.assertTrue(state.can_enter_converter)
        self.assertIn("正在扫描", progress[0])
        self.assertEqual(4, sum(message.startswith("正在检查：") for message in progress))
        self.assertTrue(any("程序指纹" in message for message in progress))
        self.assertIn("能力缓存", progress[-1])
        self.assertFalse(any("能力探测" in message for message in progress))
        self.assertEqual(0, calls["probe"])

    def test_no_candidate_and_unsupported_only_fail_with_actionable_chinese_rows(self):
        for candidates in ((), (self.unsupported,)):
            with self.subTest(candidates=candidates):
                controller, calls = self.make_controller(candidates=candidates)
                state = controller.scan()
                self.assertFalse(state.can_enter_converter)
                self.assertIsNone(state.selected)
                self.assertEqual(0, calls["probe"])
                for check in state.checks:
                    if check.status == "failure":
                        self.assertTrue(check.reason_zh.strip())
                        self.assertTrue(check.remediation_zh.strip())

    def test_manual_selection_uses_classifier_and_never_approves_unsupported(self):
        controller, calls = self.make_controller(
            classify=lambda path: self.unsupported
        )

        state = controller.select_manual(self.unsupported.executable)

        self.assertEqual(self.unsupported, state.selected)
        self.assertFalse(state.can_enter_converter)
        self.assertEqual(0, calls["save"])
        self.assertEqual(0, calls["probe"])

    def test_manual_eligible_is_saved_probed_and_approved(self):
        controller, calls = self.make_controller(
            classify=lambda path: self.eligible
        )

        state = controller.select_manual(self.executable)

        self.assertTrue(state.can_enter_converter)
        self.assertEqual(1, calls["save"])
        self.assertEqual(1, calls["probe"])

    def test_manual_missing_is_visible_but_never_saved_or_probed(self):
        missing = replace(
            self.eligible,
            executable=self.root / "missing" / "SpaceClaim.exe",
            eligibility="missing",
            reason="executable does not exist",
        )
        controller, calls = self.make_controller(classify=lambda path: missing)

        state = controller.select_manual(missing.executable)

        self.assertEqual(missing, state.selected)
        self.assertFalse(state.can_enter_converter)
        self.assertEqual(0, calls["save"])
        self.assertEqual(0, calls["probe"])

    def test_valid_cache_is_reused_without_probe_and_reprobe_bypasses_it(self):
        controller, calls = self.make_controller(
            candidates=(self.eligible,), cache=self.cache
        )

        cached_state = controller.scan()
        reprobed_state = controller.reprobe()

        self.assertEqual(Path(self.cache.probe_report), cached_state.report_path)
        self.assertEqual(0, calls["probe"] - 1)
        self.assertTrue(reprobed_state.can_enter_converter)

    def test_cache_miss_from_moved_or_replaced_identity_runs_probe(self):
        controller, calls = self.make_controller(candidates=(self.eligible,), cache=None)

        state = controller.scan()

        self.assertTrue(state.can_enter_converter)
        self.assertEqual(1, calls["probe"])

    def test_deleted_executable_identity_failure_disables_gate_without_probe(self):
        controller, calls = self.make_controller(
            candidates=(self.eligible,), identity_error=FileNotFoundError(self.executable)
        )

        state = controller.scan()

        self.assertFalse(state.can_enter_converter)
        self.assertEqual(0, calls["probe"])
        self.assertTrue(any(check.check_id == "headless_capability" and check.status == "failure" for check in state.checks))

    def test_failed_base_environment_check_prevents_probe(self):
        controller, calls = self.make_controller(candidates=(self.eligible,))
        controller._resource_probe = lambda paths: False

        state = controller.scan()

        self.assertFalse(state.can_enter_converter)
        self.assertEqual(0, calls["probe"])
        self.assertTrue(
            any(
                check.check_id == "resources" and check.status == "failure"
                for check in state.checks
            )
        )

    def test_default_resource_probe_requires_readable_utf8_with_unique_markers(self):
        probe = self.paths.resource_root / "probe_v22.py"
        worker = self.paths.resource_root / "worker_v22.py"
        probe.write_text("SENTINEL_PATH = None\n", encoding="utf-8")
        worker.write_text("MANIFEST_PATH = None\n", encoding="utf-8")
        (self.paths.resource_root / "probe_v261.py").write_text("SENTINEL_PATH = None\n", encoding="utf-8")
        (self.paths.resource_root / "worker_v261.py").write_text("MANIFEST_PATH = None\n", encoding="utf-8")
        self.assertTrue(_resources_exist(self.paths))

        worker.write_bytes(b"\xff\xfe\x00")
        self.assertFalse(_resources_exist(self.paths))

        worker.write_text("MANIFEST_PATH = None\nMANIFEST_PATH = None\n", encoding="utf-8")
        self.assertFalse(_resources_exist(self.paths))

    def test_operation_error_clears_old_authorization_and_records_reason(self):
        controller, _ = self.make_controller(candidates=(self.eligible,), cache=self.cache)
        self.assertTrue(controller.scan().can_enter_converter)

        state = controller.fail_closed(RuntimeError("resource decode failed"))

        self.assertFalse(state.can_enter_converter)
        self.assertIsNone(state.profile_path)
        failed = [check for check in state.checks if check.check_id == "headless_capability"]
        self.assertEqual(1, len(failed))
        self.assertEqual("failure", failed[0].status)
        self.assertIn("resource decode failed", failed[0].reason_zh)

    def test_probe_failure_and_timeout_preserve_report_and_disable_gate(self):
        for timed_out in (False, True):
            with self.subTest(timed_out=timed_out):
                outcome = ProbeServiceOutcome(
                    False, None, self.report, "process timed out" if timed_out else "failed", timed_out
                )
                controller, calls = self.make_controller(
                    candidates=(self.eligible,), probe_outcome=outcome
                )
                state = controller.scan()
                self.assertFalse(state.can_enter_converter)
                self.assertEqual(self.report, state.report_path)
                self.assertEqual(1, calls["probe"])

    def test_rescan_calls_discovery_again_and_prefers_previous_eligible(self):
        controller, calls = self.make_controller(
            candidates=(self.eligible,), previous=self.executable
        )

        controller.scan()
        state = controller.scan()

        self.assertEqual(2, calls["discover"])
        self.assertEqual(self.eligible, state.selected)


if __name__ == "__main__":
    unittest.main()
