from pathlib import Path
import unittest


class PackagingContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]

    def test_build_dependencies_are_exactly_pinned(self):
        pins = (self.root / "requirements-build.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            ["PyInstaller==6.21.0", "pyinstaller-hooks-contrib==2026.6"],
            pins,
        )

    def test_spec_is_one_folder_windowed_app_with_only_runtime_scripts_as_data(self):
        source = (self.root / "packaging" / "step_to_acis.spec").read_text(encoding="utf-8")
        self.assertEqual(1, source.count("EXE("))
        self.assertEqual(1, source.count("COLLECT("))
        self.assertIn("project_root = Path(SPECPATH).resolve().parent", source)
        for required in (
            "portable_launcher.py",
            'name="STEP转ACIS"',
            "console=False",
            "windows_version_info.txt",
            '"probe_v22.py"',
            '"worker_v22.py"',
            '"probe_v261.py"',
            '"worker_v261.py"',
            '"resources"',
        ):
            self.assertIn(required, source)
        for forbidden in (
            "converter_config.json",
            "spaceclaim_cli_profile.json",
            "tests",
            "tools",
            "docs/superpowers",
            ".validation",
        ):
            self.assertNotIn(forbidden, source)

    def test_build_script_cleans_bounded_paths_checks_pins_audits_and_hashes(self):
        source = (self.root / "tools" / "build_portable.ps1").read_text(encoding="utf-8")
        for required in (
            "[string]$Version",
            ".venv-build",
            "PyInstaller",
            "pyinstaller-hooks-contrib",
            "--clean",
            "--noconfirm",
            "audit_release.py",
            "Compress-Archive",
            "Get-FileHash",
            ".sha256",
            "STEP-to-ACIS-v$Version-windows-x64.zip",
            "Resolve-ChildPath",
            '"packaging\\RELEASE_NOTES_v$Version.md"',
            "Release notes are missing for version $Version",
            "(Join-Path $stagingRoot 'LICENSE')",
        ):
            self.assertIn(required, source)
        self.assertNotIn("RELEASE_NOTES_v1.0.0.md", source)
        self.assertNotIn("converter_config.json", source)
        self.assertNotIn("spaceclaim_cli_profile.json", source)

    def test_packaged_notices_and_version_metadata_exist(self):
        required = (
            "packaging/windows_version_info.txt",
            "packaging/portable_README.md",
            "packaging/RELEASE_NOTES_v1.0.1.md",
            "packaging/licenses/README.md",
            "packaging/licenses/PyInstaller-COPYING.txt",
            "packaging/licenses/Python-LICENSE.txt",
            "packaging/licenses/TclTk-LICENSE.txt",
        )
        for relative in required:
            with self.subTest(relative=relative):
                path = self.root / relative
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 100)

    def test_only_v101_release_notes_are_available_for_packaging(self):
        self.assertFalse((self.root / "packaging" / "RELEASE_NOTES_v1.0.0.md").exists())
        self.assertTrue((self.root / "packaging" / "RELEASE_NOTES_v1.0.1.md").is_file())

    def test_windows_version_metadata_is_v110_release(self):
        metadata = (self.root / "packaging" / "windows_version_info.txt").read_text(
            encoding="utf-8"
        )
        for required in (
            "filevers=(1, 1, 0, 3)",
            "prodvers=(1, 1, 0, 3)",
            "FileVersion', u'1.1.0.3",
            "ProductVersion', u'1.1.0",
        ):
            with self.subTest(required=required):
                self.assertIn(required, metadata)

    def test_windows_powershell_scripts_have_utf8_bom_for_chinese_literals(self):
        for relative in ("tools/build_portable.ps1", "tools/validate_portable.ps1"):
            with self.subTest(relative=relative):
                self.assertTrue((self.root / relative).read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_validation_script_binds_probe_evidence_to_requested_executable_identity(self):
        source = (self.root / "tools" / "validate_portable.ps1").read_text(encoding="utf-8-sig")
        for required in (
            "$requestedSpaceClaimPath",
            "$cache.identity.absolute_path",
            "SpaceClaim identity path mismatch",
            "Get-FileHash -LiteralPath $requestedSpaceClaimPath",
            "$cache.identity.sha256",
        ):
            self.assertIn(required, source)

    def test_generated_release_directories_are_ignored(self):
        ignored = (self.root / ".gitignore").read_text(encoding="utf-8").splitlines()
        for entry in (".venv-build/", "build/", "dist/", "release/"):
            self.assertIn(entry, ignored)


if __name__ == "__main__":
    unittest.main()
