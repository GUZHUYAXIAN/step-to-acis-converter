from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from step_to_acis.runtime_paths import default_runtime_paths, resource_path, resource_root


class RuntimePathTests(unittest.TestCase):
    def test_source_resources_resolve_from_module_location_not_cwd(self):
        module_file = Path(__file__).resolve().parents[1] / "src" / "step_to_acis" / "runtime_paths.py"
        root = resource_root(frozen=False, module_file=module_file)
        self.assertEqual(Path(__file__).resolve().parents[1] / "spaceclaim", root)
        self.assertEqual(root / "probe_v22.py", resource_path("probe_v22.py", root=root))
        self.assertEqual(root / "worker_v22.py", resource_path("worker_v22.py", root=root))

    def test_frozen_resources_use_meipass_resources_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            bundle = Path(temporary_directory) / "中文 bundle"
            with patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", str(bundle), create=True):
                self.assertEqual(bundle / "resources", resource_root())
                self.assertEqual(bundle / "resources" / "probe_v22.py", resource_path("probe_v22.py"))

    def test_resource_names_are_allowlisted(self):
        with self.assertRaisesRegex(ValueError, "resource"):
            resource_path("../README.md", root=Path("resources"))

    def test_state_paths_stay_below_localappdata(self):
        paths = default_runtime_paths({"LOCALAPPDATA": r"C:\Local"})
        self.assertEqual(Path(r"C:\Local\SpaceClaimStepToAcis"), paths.state_root)
        self.assertEqual(paths.state_root / "environment", paths.environment_root)
        self.assertEqual(paths.environment_root / "capability_profiles", paths.capability_profiles_root)
        self.assertEqual(paths.environment_root / "probe-runs", paths.probe_runs_root)
        self.assertEqual(paths.state_root / "gui_settings.json", paths.gui_settings_path)


if __name__ == "__main__":
    unittest.main()
