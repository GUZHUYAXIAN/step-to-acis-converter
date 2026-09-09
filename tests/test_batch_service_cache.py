from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from step_to_acis.batch_service import load_verified_capability_profile
from step_to_acis.capability_cache import (
    CachedCapability,
    executable_identity,
    save_cached_capability,
)
from step_to_acis.config import load_config
from step_to_acis.probe_runner import CliCapabilityProfile
from step_to_acis.spaceclaim_installations import SpaceClaimCandidate


class BatchServiceCacheTests(unittest.TestCase):
    def test_schema_two_cache_authorizes_matching_batch_config(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            executable = root / "v222" / "SCDM" / "SpaceClaim.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"verified")
            input_dir = root / "input"
            input_dir.mkdir()
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "spaceclaim_exe": str(executable),
                        "input_dir": str(input_dir),
                        "output_dir": str(root / "output"),
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(config_path)
            identity = executable_identity(
                SpaceClaimCandidate(
                    executable,
                    "2022.2.0.0",
                    "2022.2.1.2",
                    "v222",
                    (),
                    "eligible",
                    "eligible",
                )
            )
            profile = CliCapabilityProfile(
                True, True, True, True, False, True, "specialized_worker_literal"
            )
            cache = root / "profile.json"
            save_cached_capability(
                cache,
                CachedCapability(identity, profile, True, "report.json", "now"),
            )

            with patch(
                "step_to_acis.batch_service.read_file_version",
                return_value=type(
                    "Version",
                    (),
                    {
                        "product_version": "2022.2.0.0",
                        "file_version": "2022.2.1.2",
                    },
                )(),
            ):
                loaded = load_verified_capability_profile(cache, config)

        self.assertEqual(profile, loaded)


if __name__ == "__main__":
    unittest.main()
