from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from step_to_acis.gui import ConverterGui
from step_to_acis.gui_models import GuiFormValues
from step_to_acis.gui_settings import save_gui_settings


class FakeRoot:
    def __init__(self):
        self.after_calls = []
        self.protocol_calls = []
        self.destroy_calls = 0

    def after(self, delay, callback):
        self.after_calls.append((delay, callback))

    def protocol(self, name, callback):
        self.protocol_calls.append((name, callback))

    def destroy(self):
        self.destroy_calls += 1


class FakeView:
    def __init__(self, root, values):
        self.values = values
        self.advanced_visible = False
        self.warning_visible = values.overwrite_policy == "Overwrite"
        self.enabled_history = []
        self.errors = []

    def get_form_values(self):
        return self.values

    def set_controls_enabled(self, enabled):
        self.enabled_history.append(enabled)

    def show_error(self, message):
        self.errors.append(message)

    def toggle_advanced(self):
        self.advanced_visible = not self.advanced_visible

    def update_overwrite_warning(self):
        self.warning_visible = self.values.overwrite_policy == "Overwrite"


class FakeThread:
    def __init__(self, *, target, daemon):
        self.target = target
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True


class ConverterGuiConstructionTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temporary_directory.name)
        self.input_dir = self.root_dir / "input"
        self.output_dir = self.root_dir / "output"
        self.input_dir.mkdir()
        self.executable = self.root_dir / "SpaceClaim.exe"
        self.executable.write_bytes(b"fake")
        self.config_path = self.root_dir / "config.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "spaceclaim_exe": str(self.executable),
                    "input_dir": str(self.input_dir),
                    "output_dir": str(self.output_dir),
                }
            ),
            encoding="utf-8",
        )
        self.profile_path = self.root_dir / "profile.json"
        self.settings_path = self.root_dir / "settings.json"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def make_gui(self, **overrides):
        root = FakeRoot()
        threads = []

        def thread_factory(**kwargs):
            thread = FakeThread(**kwargs)
            threads.append(thread)
            return thread

        gui = ConverterGui(
            root,
            config_path=self.config_path,
            capability_profile_path=self.profile_path,
            settings_path=self.settings_path,
            thread_factory=thread_factory,
            view_factory=FakeView,
            **overrides,
        )
        return gui, root, threads

    def test_safe_defaults_populate_form_and_advanced_starts_hidden(self):
        gui, _, _ = self.make_gui()

        values = gui.view.values
        self.assertEqual("SAB", values.output_format)
        self.assertEqual("Skip", values.overwrite_policy)
        self.assertEqual("V22", values.acis_version)
        self.assertEqual(20, values.chunk_size)
        self.assertEqual(900.0, values.timeout_seconds)
        self.assertEqual(0, values.retry_count)
        self.assertFalse(gui.view.advanced_visible)

    def test_saved_settings_override_defaults(self):
        saved = GuiFormValues(
            input_dir=str(self.input_dir),
            output_dir=str(self.output_dir),
            output_format="SAT",
            recursive=True,
            overwrite_policy="Overwrite",
            acis_version="V23",
            chunk_size=8,
            timeout_seconds=75.0,
            retry_count=1,
        )
        save_gui_settings(self.settings_path, saved)

        gui, _, _ = self.make_gui()

        self.assertEqual(saved, gui.view.values)

    def test_advanced_toggle_preserves_values_and_overwrite_controls_warning(self):
        gui, _, _ = self.make_gui()
        before = gui.view.values

        gui.toggle_advanced()
        gui.toggle_advanced()

        self.assertFalse(gui.view.advanced_visible)
        self.assertEqual(before, gui.view.values)
        gui.view.values = replace(gui.view.values, overwrite_policy="Overwrite")
        gui.update_overwrite_warning()
        self.assertTrue(gui.view.warning_visible)
        gui.view.values = replace(gui.view.values, overwrite_policy="Skip")
        gui.update_overwrite_warning()
        self.assertFalse(gui.view.warning_visible)

    def test_start_saves_values_disables_controls_and_launches_one_daemon_thread(self):
        gui, _, threads = self.make_gui()

        gui.start_conversion()

        self.assertEqual([False], gui.view.enabled_history)
        self.assertEqual(1, len(threads))
        self.assertTrue(threads[0].daemon)
        self.assertTrue(threads[0].started)
        self.assertEqual(gui.view.values, __import__("step_to_acis.gui_settings", fromlist=["load_gui_settings"]).load_gui_settings(self.settings_path, gui.view.values))

        gui.start_conversion()
        self.assertEqual(1, len(threads))

    def test_invalid_form_shows_error_and_launches_no_thread(self):
        gui, _, threads = self.make_gui()
        gui.view.values = replace(gui.view.values, input_dir="")

        gui.start_conversion()

        self.assertEqual([], threads)
        self.assertTrue(gui.view.errors)
        self.assertIn("input_dir", gui.view.errors[-1])


if __name__ == "__main__":
    unittest.main()
