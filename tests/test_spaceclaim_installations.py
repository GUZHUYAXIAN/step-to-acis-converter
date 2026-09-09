from pathlib import Path
import tempfile
import unittest

from step_to_acis.spaceclaim_installations import (
    candidate_paths,
    classify_candidate,
    discover_spaceclaim,
    validate_manual_selection,
)
from step_to_acis.windows_file_version import FileVersionError, FileVersionInfo


class SpaceClaimInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def executable(self, version="v222", base=None):
        root = self.root if base is None else base
        path = root / "ANSYS Inc" / version / "SCDM" / "SpaceClaim.exe"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(version.encode("ascii"))
        return path

    @staticmethod
    def verified_reader(path):
        return FileVersionInfo("2022.2.0.0", "2022.2.45056.55939")

    def test_candidate_sources_are_bounded_deduplicated_and_merged(self):
        executable = self.executable()
        previous = Path(str(executable).upper())

        candidates = candidate_paths(
            environ={"AWP_ROOT222": str(executable.parents[1])},
            drive_roots=(self.root,),
            registry_values=(str(executable),),
            previous=previous,
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual(executable.resolve(), candidates[0][0].resolve())
        self.assertEqual(
            {"environment", "fixed_drive", "previous", "registry"},
            set(candidates[0][1]),
        )

    def test_classification_approves_only_v222_with_2022_2_metadata(self):
        eligible = classify_candidate(
            self.executable("v222"), version_reader=self.verified_reader
        )
        wrong_layout = classify_candidate(
            self.executable("v231"), version_reader=self.verified_reader
        )
        mismatch = classify_candidate(
            self.executable("v222", self.root / "other"),
            version_reader=lambda path: FileVersionInfo("2023.1.0.0", "2023.1.2.3"),
        )

        self.assertEqual("eligible", eligible.eligibility)
        self.assertEqual("v222", eligible.layout_version)
        self.assertEqual("unsupported", wrong_layout.eligibility)
        self.assertIn("v222", wrong_layout.reason)
        self.assertEqual("unsupported", mismatch.eligibility)
        self.assertIn("2022 R2", mismatch.reason)

    def test_unreadable_and_missing_candidates_fail_closed(self):
        unreadable = classify_candidate(
            self.executable(),
            version_reader=lambda path: (_ for _ in ()).throw(FileVersionError("denied")),
        )
        missing = classify_candidate(
            self.root / "missing" / "ANSYS Inc" / "v222" / "SCDM" / "SpaceClaim.exe",
            version_reader=self.verified_reader,
        )

        self.assertEqual("unreadable", unreadable.eligibility)
        self.assertIn("denied", unreadable.reason)
        self.assertEqual("missing", missing.eligibility)

    def test_discovery_records_unsupported_but_sorts_eligible_first(self):
        v231 = self.executable("v231")
        v222 = self.executable("v222")

        discovered = discover_spaceclaim(
            environ={},
            previous=None,
            registry_reader=lambda: (),
            drives_reader=lambda: (self.root,),
            version_reader=self.verified_reader,
        )

        self.assertEqual([v222.resolve(), v231.resolve()], [item.executable.resolve() for item in discovered])
        self.assertEqual(["eligible", "unsupported"], [item.eligibility for item in discovered])

    def test_manual_selection_uses_same_validation_path(self):
        eligible = validate_manual_selection(
            self.executable(), version_reader=self.verified_reader
        )
        unsupported = validate_manual_selection(
            self.executable("v221"), version_reader=self.verified_reader
        )

        self.assertEqual("eligible", eligible.eligibility)
        self.assertEqual("unsupported", unsupported.eligibility)


if __name__ == "__main__":
    unittest.main()
