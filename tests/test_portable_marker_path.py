from pathlib import Path
import unittest

from step_to_acis.portable_config import portable_paths_marker_path
from step_to_acis.runtime_paths import RuntimePaths


class PortableMarkerPathTests(unittest.TestCase):
    def test_marker_is_local_state_not_a_packaged_resource(self):
        state_root = Path(r"C:\Local\SpaceClaimStepToAcis")
        paths = RuntimePaths(
            resource_root=Path(r"E:\bundle\resources"),
            state_root=state_root,
            environment_root=state_root / "environment",
            capability_profiles_root=state_root / "environment" / "capability_profiles",
            probe_runs_root=state_root / "environment" / "probe-runs",
            gui_settings_path=state_root / "gui_settings.json",
        )

        self.assertEqual(
            state_root / "portable_paths.json",
            portable_paths_marker_path(paths),
        )


if __name__ == "__main__":
    unittest.main()
