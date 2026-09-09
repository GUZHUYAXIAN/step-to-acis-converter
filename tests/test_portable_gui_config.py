from pathlib import Path
import tempfile
import unittest

from step_to_acis.gui import ConverterGui
from step_to_acis.gui_models import GuiFormValues
from step_to_acis.gui_settings import load_gui_settings, save_gui_settings
from tests.test_gui import FakeRoot, FakeThread, FakeView


class PortableGuiConfigTests(unittest.TestCase):
    def test_settings_loader_can_keep_preferences_but_suppress_saved_paths(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "gui_settings.json"
            defaults = GuiFormValues(input_dir="", output_dir="")
            saved = GuiFormValues(
                input_dir=r"E:\old input",
                output_dir=r"E:\old output",
                output_format="SAT",
                recursive=True,
            )
            save_gui_settings(path, saved)

            loaded = load_gui_settings(path, defaults, restore_paths=False)

            self.assertEqual("", loaded.input_dir)
            self.assertEqual("", loaded.output_dir)
            self.assertEqual("SAT", loaded.output_format)
            self.assertTrue(loaded.recursive)

    def test_portable_gui_uses_injected_blank_defaults_without_loading_config(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root_dir = Path(temporary_directory)
            settings = root_dir / "gui_settings.json"
            save_gui_settings(
                settings,
                GuiFormValues(input_dir=r"E:\old", output_dir=r"E:\old-output"),
            )
            gui = ConverterGui(
                FakeRoot(),
                config_path=root_dir / "missing-runtime-config.json",
                capability_profile_path=root_dir / "profile.json",
                settings_path=settings,
                defaults=GuiFormValues(input_dir="", output_dir=""),
                restore_saved_paths=False,
                view_factory=FakeView,
            )

            self.assertEqual("", gui.view.values.input_dir)
            self.assertEqual("", gui.view.values.output_dir)

    def test_acceptance_callback_runs_only_after_valid_settings_save(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root_dir = Path(temporary_directory)
            input_dir = root_dir / "input"
            input_dir.mkdir()
            executable = root_dir / "SpaceClaim.exe"
            executable.write_bytes(b"fake")
            config_path = root_dir / "runtime.json"
            from step_to_acis.portable_config import write_portable_config
            write_portable_config(config_path, executable)
            callbacks = []
            threads = []

            def thread_factory(**kwargs):
                thread = FakeThread(**kwargs)
                threads.append(thread)
                return thread

            gui = ConverterGui(
                FakeRoot(),
                config_path=config_path,
                capability_profile_path=root_dir / "profile.json",
                settings_path=root_dir / "gui_settings.json",
                defaults=GuiFormValues(input_dir="", output_dir=""),
                restore_saved_paths=False,
                on_settings_saved=lambda: callbacks.append("accepted"),
                thread_factory=thread_factory,
                view_factory=FakeView,
            )
            gui.start_conversion()
            self.assertEqual([], callbacks)
            self.assertEqual([], threads)

            gui.view.values = GuiFormValues(
                input_dir=str(input_dir),
                output_dir=str(root_dir / "output"),
            )
            gui.start_conversion()

            self.assertEqual(["accepted"], callbacks)
            self.assertEqual(1, len(threads))


if __name__ == "__main__":
    unittest.main()
