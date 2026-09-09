from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.audit_release import AuditError, audit_release


class ReleaseAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.repo = self.root / "private repo"
        self.repo.mkdir()
        self.staging = self.root / "STEP转ACIS便携版"
        (self.staging / "_internal" / "resources").mkdir(parents=True)
        (self.staging / "licenses").mkdir()
        (self.staging / "STEP转ACIS.exe").write_bytes(b"MZ-safe")
        (self.staging / "README.md").write_text("用户说明", encoding="utf-8")
        (self.staging / "RELEASE_NOTES.md").write_text("发行说明", encoding="utf-8")
        (self.staging / "LICENSE").write_text("MIT License", encoding="utf-8")
        (self.staging / "licenses" / "LICENSE.txt").write_text("license", encoding="utf-8")
        for name in ("probe_v22.py", "worker_v22.py"):
            (self.staging / "_internal" / "resources" / name).write_text("safe", encoding="utf-8")
        (self.staging / "_internal" / "python312.dll").write_bytes(b"runtime")
        self.zip_path = self.root / "release.zip"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_zip(self, excluded=()):
        excluded = set(excluded)
        with zipfile.ZipFile(self.zip_path, "w") as archive:
            for path in self.staging.rglob("*"):
                if path.is_file():
                    relative = path.relative_to(self.staging).as_posix()
                    if relative not in excluded:
                        archive.write(path, relative)

    def test_clean_staging_and_zip_pass(self):
        self.write_zip()
        audit_release(self.staging, self.zip_path, self.repo)

    def test_forbidden_names_and_extensions_fail(self):
        forbidden = (
            ".git/config",
            ".worktrees/linked",
            "tests/test.py",
            "tools/helper.py",
            "docs/superpowers/plan.md",
            ".validation/evidence.txt",
            "conversion_logs/run.txt",
            "gui_settings.json",
            "selected_spaceclaim.json",
            "capability_profiles/cache.json",
            "probe-runs/report.json",
            "converter_config.json",
            "spaceclaim_cli_profile.json",
            "user.step",
            "user.stp",
            "output.sab",
            "output.sat",
            "report.csv",
            "run.log",
        )
        for relative in forbidden:
            with self.subTest(relative=relative):
                path = self.staging / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("bad", encoding="utf-8")
                self.write_zip()
                with self.assertRaises(AuditError):
                    audit_release(self.staging, self.zip_path, self.repo)
                path.unlink()

    def test_private_repo_path_in_utf8_or_utf16le_fails(self):
        private = str(self.repo.resolve())
        for encoding in ("utf-8", "utf-16le"):
            with self.subTest(encoding=encoding):
                leak = self.staging / "_internal" / "leak.bin"
                leak.write_bytes(private.encode(encoding))
                self.write_zip()
                with self.assertRaises(AuditError):
                    audit_release(self.staging, self.zip_path, self.repo)
                leak.unlink()

    def test_missing_staging_project_license_fails(self):
        (self.staging / "LICENSE").unlink()
        with self.assertRaises(AuditError):
            audit_release(self.staging, None, self.repo)

    def test_missing_zip_project_license_fails_after_valid_staging_audit(self):
        self.write_zip(excluded={"LICENSE"})
        with self.assertRaises(AuditError):
            audit_release(self.staging, self.zip_path, self.repo)

    def test_unexpected_resource_fails(self):
        (self.staging / "_internal" / "resources" / "secret.txt").write_text("bad", encoding="utf-8")
        self.write_zip()
        with self.assertRaises(AuditError):
            audit_release(self.staging, self.zip_path, self.repo)


if __name__ == "__main__":
    unittest.main()
