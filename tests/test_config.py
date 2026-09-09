import json
from pathlib import Path
import tempfile
import unittest

from step_to_acis.config import ConfigError, load_config
from step_to_acis.models import OutputFormat, OverwritePolicy


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.executable = self.root / "SpaceClaim.exe"
        self.executable.write_bytes(b"exe")
        self.input_dir = self.root / "input"
        self.input_dir.mkdir()
        self.output_dir = self.root / "output"
        self.config_path = self.root / "config.json"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_config(self, **updates):
        payload = {
            "spaceclaim_exe": str(self.executable),
            "input_dir": str(self.input_dir),
            "output_dir": str(self.output_dir),
        }
        payload.update(updates)
        self.config_path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_safe_defaults_are_sab_skip_and_explicit_v22(self):
        self.write_config()

        config = load_config(self.config_path)

        self.assertEqual((OutputFormat.SAB,), config.acis.output_formats)
        self.assertEqual(OverwritePolicy.SKIP, config.overwrite_policy)
        self.assertEqual("V22", config.acis.version)
        self.assertEqual("V22", config.resolved_acis_version)
        self.assertEqual("Millimeters", config.acis.units)
        self.assertFalse(config.recursive)
        self.assertEqual(20, config.chunk_size)
        self.assertEqual(0, config.retry_count)
        self.assertTrue(config.preserve_relative_directories)

    def test_legacy_current_default_alias_still_resolves_to_v22(self):
        self.write_config(acis_version="current_spaceclaim_default")

        config = load_config(self.config_path)

        self.assertEqual("current_spaceclaim_default", config.acis.version)
        self.assertEqual("V22", config.resolved_acis_version)

    def test_checked_in_example_uses_explicit_v22(self):
        repository_root = Path(__file__).resolve().parents[1]

        payload = json.loads(
            (repository_root / "converter_config.example.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual("V22", payload["acis_version"])

    def test_formats_structurally_allow_sat_or_both(self):
        self.write_config(output_formats=["SAT"])
        sat = load_config(self.config_path)
        self.write_config(output_formats=["SAB", "SAT"])
        both = load_config(self.config_path)

        self.assertEqual((OutputFormat.SAT,), sat.acis.output_formats)
        self.assertEqual((OutputFormat.SAB, OutputFormat.SAT), both.acis.output_formats)

    def test_cli_overrides_replace_common_values(self):
        self.write_config()

        config = load_config(
            self.config_path,
            {
                "recursive": True,
                "output_formats": ["SAT"],
                "overwrite_policy": "Overwrite",
                "chunk_size": 7,
            },
        )

        self.assertTrue(config.recursive)
        self.assertEqual((OutputFormat.SAT,), config.acis.output_formats)
        self.assertEqual(OverwritePolicy.OVERWRITE, config.overwrite_policy)
        self.assertEqual(7, config.chunk_size)

    def test_unknown_keys_are_rejected_but_comment_keys_are_allowed(self):
        self.write_config(_comment_usage="example", mystery=True)

        with self.assertRaisesRegex(ConfigError, "unknown configuration key: mystery"):
            load_config(self.config_path)

        self.write_config(_comment_usage="example")
        config = load_config(self.config_path)
        self.assertEqual(self.input_dir.resolve(), config.input_dir)

    def test_input_and_output_must_be_distinct_after_normalization(self):
        self.write_config(output_dir=str(self.input_dir / ".." / "input"))

        with self.assertRaisesRegex(ConfigError, "input_dir and output_dir must be distinct"):
            load_config(self.config_path)

    def test_invalid_values_have_field_specific_errors(self):
        invalid_cases = [
            ({"output_formats": []}, "output_formats"),
            ({"output_formats": ["IGES"]}, "output_formats"),
            ({"overwrite_policy": "Replace"}, "overwrite_policy"),
            ({"acis_version": "V14"}, "acis_version"),
            ({"acis_units": "Microns"}, "acis_units"),
            ({"chunk_size": 0}, "chunk_size"),
            ({"chunk_size": 101}, "chunk_size"),
            ({"heartbeat_timeout_seconds": 0}, "heartbeat_timeout_seconds"),
            ({"retry_count": 2}, "retry_count"),
            ({"recursive": "yes"}, "recursive"),
        ]

        for updates, field in invalid_cases:
            with self.subTest(field=field, value=updates[field]):
                self.write_config(**updates)
                with self.assertRaisesRegex(ConfigError, field):
                    load_config(self.config_path)

    def test_v22_supported_acis_versions_are_accepted(self):
        for version in ["V6", "V7", "V15", "V22", "V31"]:
            with self.subTest(version=version):
                self.write_config(acis_version=version)
                self.assertEqual(version, load_config(self.config_path).resolved_acis_version)

    def test_missing_paths_fail_before_spaceclaim_launch(self):
        self.write_config(spaceclaim_exe=str(self.root / "missing.exe"))
        with self.assertRaisesRegex(ConfigError, "spaceclaim_exe"):
            load_config(self.config_path)

        self.write_config(input_dir=str(self.root / "missing-input"))
        with self.assertRaisesRegex(ConfigError, "input_dir"):
            load_config(self.config_path)
