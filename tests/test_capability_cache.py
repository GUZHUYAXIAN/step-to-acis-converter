from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from step_to_acis.capability_cache import (
    CachedCapability,
    cache_path,
    executable_identity,
    load_cached_capability,
    load_selected_executable,
    save_cached_capability,
    save_selected_executable,
)
from step_to_acis.probe_runner import CliCapabilityProfile
from step_to_acis.spaceclaim_installations import SpaceClaimCandidate


class CapabilityCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.executable = self.root / "v222" / "SCDM" / "SpaceClaim.exe"
        self.executable.parent.mkdir(parents=True)
        self.executable.write_bytes(b"verified executable")
        self.candidate = SpaceClaimCandidate(
            self.executable.resolve(),
            "2022.2.0.0",
            "2022.2.45056.55939",
            "v222",
            ("manual",),
            "eligible",
            "eligible",
        )
        self.identity = executable_identity(self.candidate)
        self.profile = CliCapabilityProfile(
            True, True, True, True, False, True, "specialized_worker_literal"
        )
        self.cached = CachedCapability(
            self.identity,
            self.profile,
            True,
            str(self.root / "probe_report.json"),
            "2026-08-12T00:00:00+00:00",
        )
        self.path = cache_path(self.root / "profiles", self.identity)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_identity_hash_and_cache_path_are_content_based(self):
        self.assertEqual(64, len(self.identity.sha256))
        self.assertEqual(self.identity.sha256, self.identity.sha256.upper())
        self.assertEqual(self.identity.sha256 + ".json", self.path.name)

    def test_valid_cache_round_trips(self):
        save_cached_capability(self.path, self.cached)
        self.assertEqual(self.cached, load_cached_capability(self.path, self.identity))

    def test_path_hash_version_and_deleted_executable_invalidate(self):
        save_cached_capability(self.path, self.cached)
        mismatches = [
            replace(self.identity, absolute_path=str(self.root / "moved" / "SpaceClaim.exe")),
            replace(self.identity, sha256="0" * 64),
            replace(self.identity, product_version="2022.2.9.9"),
            replace(self.identity, file_version="2022.2.9.9"),
        ]
        for current in mismatches:
            with self.subTest(current=current):
                self.assertIsNone(load_cached_capability(self.path, current))
        self.executable.unlink()
        self.assertIsNone(load_cached_capability(self.path, self.identity))

    def test_corrupt_incomplete_and_unproven_cache_fail_closed(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{broken", encoding="utf-8")
        self.assertIsNone(load_cached_capability(self.path, self.identity))

        save_cached_capability(self.path, replace(self.cached, probe_completed=False))
        self.assertIsNone(load_cached_capability(self.path, self.identity))

        unsafe = replace(self.profile, headless=False)
        save_cached_capability(self.path, replace(self.cached, profile=unsafe))
        self.assertIsNone(load_cached_capability(self.path, self.identity))

        wrong_strategy = replace(self.profile, script_args_strategy="sys.argv[1]")
        save_cached_capability(self.path, replace(self.cached, profile=wrong_strategy))
        self.assertIsNone(load_cached_capability(self.path, self.identity))

    def test_save_is_atomic_and_replace_failure_preserves_target(self):
        save_cached_capability(self.path, self.cached)
        before = self.path.read_bytes()
        with patch("step_to_acis.capability_cache.os.replace", side_effect=OSError("denied")):
            with self.assertRaisesRegex(OSError, "denied"):
                save_cached_capability(self.path, replace(self.cached, verified_at="later"))
        self.assertEqual(before, self.path.read_bytes())
        self.assertFalse(self.path.with_name(self.path.name + ".tmp").exists())

    def test_selected_executable_round_trip_and_deletion(self):
        selected = self.root / "selected_spaceclaim.json"
        save_selected_executable(selected, self.identity)
        self.assertEqual(self.executable.resolve(), load_selected_executable(selected))
        self.executable.unlink()
        self.assertIsNone(load_selected_executable(selected))
        selected.write_text(json.dumps({"schema": 999}), encoding="utf-8")
        self.assertIsNone(load_selected_executable(selected))


if __name__ == "__main__":
    unittest.main()
