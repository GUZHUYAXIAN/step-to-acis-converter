import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

from step_to_acis.environment_models import REQUIRED_CHECK_IDS, CheckResult, EnvironmentState
from step_to_acis.gui_models import GuiFormValues
from step_to_acis.portable_main import launch_converter, main
from step_to_acis.runtime_paths import RuntimePaths
from step_to_acis.spaceclaim_installations import SpaceClaimCandidate


class FakeRoot:
    def __init__(self, order=None):
        self.order = order if order is not None else []
        self.titles = []
        self.mainloop_calls = 0

    def title(self, value):
        self.titles.append(value)

    def mainloop(self):
        self.mainloop_calls += 1


class PortableMainTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temporary_directory.name)
        resources = self.root_dir / "resources"
        resources.mkdir()
        for name in ("probe_v22.py", "worker_v22.py", "probe_v261.py", "worker_v261.py"):
            (resources / name).write_text("resource", encoding="utf-8")
        state_root = self.root_dir / "state"
        self.paths = RuntimePaths(
            resources,
            state_root,
            state_root / "environment",
            state_root / "environment" / "capability_profiles",
            state_root / "environment" / "probe-runs",
            state_root / "gui_settings.json",
        )
        self.executable = self.root_dir / "v222" / "SCDM" / "SpaceClaim.exe"
        self.executable.parent.mkdir(parents=True)
        self.executable.write_bytes(b"exe")
        candidate = SpaceClaimCandidate(
            self.executable,
            "2022.2.0.0",
            "2022.2.1.0",
            "v222",
            ("manual",),
            "eligible",
            "eligible",
        )
        self.profile_path = self.paths.capability_profiles_root / ("A" * 64 + ".json")
        checks = tuple(
            CheckResult(check_id, "required", "pass", "通过", "原因", "建议")
            for check_id in REQUIRED_CHECK_IDS
        )
        self.approved = EnvironmentState(
            candidates=(candidate,),
            selected=candidate,
            checks=checks,
            profile_path=self.profile_path,
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_launch_writes_generic_config_and_passes_blank_safe_runtime_inputs(self):
        captured = {}

        class FakeConverter:
            def __init__(self, root, **kwargs):
                captured.update(kwargs)

        converter = launch_converter(
            FakeRoot(), self.approved, self.paths, converter_factory=FakeConverter
        )

        self.assertIsInstance(converter, FakeConverter)
        config = json.loads(captured["config_path"].read_text(encoding="utf-8"))
        self.assertEqual(str(self.executable.resolve()), config["spaceclaim_exe"])
        self.assertEqual("", config["input_dir"])
        self.assertEqual("", config["output_dir"])
        self.assertEqual(["SAB"], config["output_formats"])
        self.assertEqual("Skip", config["overwrite_policy"])
        self.assertEqual("V22", config["acis_version"])
        self.assertEqual("Millimeters", config["acis_units"])
        self.assertEqual(self.profile_path, captured["capability_profile_path"])
        self.assertEqual(self.paths.resource_root / "worker_v22.py", captured["worker_template_path"])
        self.assertEqual(GuiFormValues(input_dir="", output_dir=""), captured["defaults"])
        self.assertFalse(captured["restore_saved_paths"])

    def test_unapproved_state_cannot_construct_converter(self):
        with self.assertRaises(ValueError):
            launch_converter(
                FakeRoot(),
                EnvironmentState(selected=self.approved.selected),
                self.paths,
                converter_factory=lambda *args, **kwargs: self.fail("constructed"),
            )

    def test_main_constructs_self_check_first_then_destroys_it_before_converter(self):
        order = []
        root = FakeRoot(order)

        class FakeController:
            def __init__(self, paths):
                order.append("controller")

        class FakeCheckGui:
            def __init__(self, root, *, controller, on_approved):
                order.append("self-check")
                self.on_approved = on_approved

            def rescan(self):
                order.append("scan")
                self.on_approved(self_approved)

            def poll_events(self):
                order.append("self-check-poll")

            def destroy(self):
                order.append("self-check-destroy")

        class FakeConverter:
            def __init__(self, root, **kwargs):
                order.append("converter")

            def poll_events(self):
                order.append("converter-poll")

        self_approved = self.approved
        with patch("step_to_acis.portable_main.tk.Tk", return_value=root), patch(
            "step_to_acis.portable_main.default_runtime_paths", return_value=self.paths
        ), patch("step_to_acis.portable_main.EnvironmentController", FakeController), patch(
            "step_to_acis.portable_main.EnvironmentCheckGui", FakeCheckGui
        ), patch("step_to_acis.portable_main.ConverterGui", FakeConverter):
            result = main()

        self.assertEqual(0, result)
        self.assertLess(order.index("self-check"), order.index("converter"))
        self.assertLess(order.index("self-check-destroy"), order.index("converter"))
        self.assertEqual(1, root.mainloop_calls)
        self.assertEqual("STEP → ACIS 环境自检", root.titles[0])

    def test_portable_launcher_is_the_thin_only_user_entry(self):
        source = (Path(__file__).resolve().parents[1] / "portable_launcher.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("from step_to_acis.portable_main import main", source)
        self.assertIn("raise SystemExit(main())", source)

    def test_windowed_entry_provides_streams_before_constructing_gui(self):
        def run_gui(paths):
            self.assertEqual(self.paths, paths)
            print("GUI startup")
            sys.stderr.write("GUI diagnostic\n")
            return 0

        with patch("step_to_acis.portable_main.default_runtime_paths", return_value=self.paths), patch(
            "step_to_acis.portable_main._run_gui", side_effect=run_gui
        ), patch.object(sys, "stdout", None), patch.object(sys, "stderr", None):
            self.assertEqual(0, main())
        logs = list((self.paths.state_root / "logs").glob("*.log"))
        self.assertIn("GUI diagnostic", logs[0].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
