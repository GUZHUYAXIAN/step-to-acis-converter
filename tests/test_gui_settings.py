from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from step_to_acis.gui_models import GuiFormValues
from step_to_acis.gui_settings import default_settings_path, load_gui_settings, save_gui_settings


class GuiSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.path = self.root / "nested" / "gui_settings.json"
        self.defaults = GuiFormValues(
            input_dir=r"E:\默认 STEP",
            output_dir=r"E:\默认 ACIS",
        )
        self.values = GuiFormValues(
            input_dir=r"E:\中文 STEP folder",
            output_dir=r"E:\中文 ACIS folder",
            output_format="SAT",
            recursive=True,
            overwrite_policy="Overwrite",
            acis_version="V23",
            chunk_size=10,
            timeout_seconds=60.5,
            retry_count=1,
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_default_path_uses_localappdata(self):
        self.assertEqual(
            Path(r"C:\Local\SpaceClaimStepToAcis\gui_settings.json"),
            default_settings_path({"LOCALAPPDATA": r"C:\Local"}),
        )

    def test_default_path_falls_back_below_user_home(self):
        with patch("step_to_acis.gui_settings.Path.home", return_value=Path(r"C:\workspace\Test")):
            path = default_settings_path({})

        self.assertEqual(
            Path(r"C:\workspace\Test\AppData\Local\SpaceClaimStepToAcis\gui_settings.json"),
            path,
        )

    def test_absent_and_malformed_files_return_defaults(self):
        self.assertEqual(self.defaults, load_gui_settings(self.path, self.defaults))
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{broken", encoding="utf-8")
        self.assertEqual(self.defaults, load_gui_settings(self.path, self.defaults))

    def test_valid_utf8_settings_round_trip_all_fields(self):
        save_gui_settings(self.path, self.values)

        self.assertEqual(self.values, load_gui_settings(self.path, self.defaults))
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(asdict(self.values), payload)
        self.assertIn("中文 STEP folder", self.path.read_text(encoding="utf-8"))

    def test_invalid_fields_fall_back_independently(self):
        self.path.parent.mkdir(parents=True)
        payload = asdict(self.defaults)
        payload.update(
            {
                "output_format": "SAT",
                "recursive": True,
                "chunk_size": 0,
                "retry_count": "once",
                "unknown": "ignored",
            }
        )
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        loaded = load_gui_settings(self.path, self.defaults)

        self.assertEqual("SAT", loaded.output_format)
        self.assertTrue(loaded.recursive)
        self.assertEqual(self.defaults.chunk_size, loaded.chunk_size)
        self.assertEqual(self.defaults.retry_count, loaded.retry_count)

    def test_valid_saved_input_output_pair_is_restored_atomically(self):
        self.path.parent.mkdir(parents=True)
        saved_input = self.defaults.output_dir
        saved_output = r"E:\第三个目录"
        payload = asdict(self.defaults)
        payload.update(
            {
                "input_dir": saved_input,
                "output_dir": saved_output,
            }
        )
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        loaded = load_gui_settings(self.path, self.defaults)

        self.assertEqual(saved_input, loaded.input_dir)
        self.assertEqual(saved_output, loaded.output_dir)

    def test_save_fsyncs_temporary_file_replaces_target_and_leaves_no_tmp(self):
        real_replace = os.replace
        with patch("step_to_acis.gui_settings.os.fsync", wraps=os.fsync) as fsync_spy, patch(
            "step_to_acis.gui_settings.os.replace", wraps=real_replace
        ) as replace_spy:
            save_gui_settings(self.path, self.values)

        self.assertEqual(1, fsync_spy.call_count)
        self.assertEqual(1, replace_spy.call_count)
        source, target = replace_spy.call_args.args
        self.assertEqual(self.path.with_name("gui_settings.json.tmp"), source)
        self.assertEqual(self.path, target)
        self.assertFalse(self.path.with_name("gui_settings.json.tmp").exists())

    def test_replace_failure_preserves_previous_target(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"previous": true}', encoding="utf-8")

        with patch("step_to_acis.gui_settings.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaisesRegex(OSError, "replace failed"):
                save_gui_settings(self.path, self.values)

        self.assertEqual('{"previous": true}', self.path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
