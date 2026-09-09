import os
from pathlib import Path
import subprocess
import unittest


class BatContractTests(unittest.TestCase):
    def test_missing_python_message_states_actual_minimum_version(self):
        repository_root = Path(__file__).resolve().parents[1]
        source = (repository_root / "run_converter.bat").read_text(encoding="utf-8")

        self.assertIn("Python 3.10 or newer", source)
        self.assertNotIn("Python 3.8 or newer", source)
        self.assertIn("sys.version_info >= (3,10)", source)

    def test_bat_launches_cli_help_and_preserves_exit_code(self):
        repository_root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment["STEP_TO_ACIS_NO_PAUSE"] = "1"

        result = subprocess.run(
            ["cmd", "/c", str(repository_root / "run_converter.bat"), "--help"],
            cwd=repository_root,
            env=environment,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("STEP", result.stdout)
        self.assertIn("SAB", result.stdout)
        self.assertIn("Skip", result.stdout)

    def test_bat_passes_arguments_to_cli(self):
        repository_root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment["STEP_TO_ACIS_NO_PAUSE"] = "1"

        result = subprocess.run(
            [
                "cmd",
                "/c",
                str(repository_root / "run_converter.bat"),
                "--config",
                str(repository_root / "missing-config.json"),
            ],
            cwd=repository_root,
            env=environment,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("missing-config.json", result.stderr)

    def test_gui_bat_keeps_console_attached_and_preserves_exit_contract(self):
        repository_root = Path(__file__).resolve().parents[1]
        source = (repository_root / "run_converter_gui.bat").read_text(encoding="utf-8")
        lowered = source.lower()

        self.assertIn("sys.version_info >= (3,10)", source)
        self.assertIn('set "PYTHONPATH=%TOOL_DIR%src"', source)
        self.assertIn("py -3 -X utf8 -m step_to_acis.gui_main", source)
        self.assertIn("python -X utf8 -m step_to_acis.gui_main", source)
        self.assertIn('"%CODEX_PYTHON%" -X utf8 -m step_to_acis.gui_main', source)
        self.assertNotIn("run_converter.bat", lowered)
        self.assertNotIn("pythonw", lowered)
        self.assertNotIn("start ", lowered)
        self.assertNotIn(" /b", lowered)
        self.assertIn('set "EXIT_CODE=%ERRORLEVEL%"', source)
        self.assertIn("STEP_TO_ACIS_NO_PAUSE", source)


if __name__ == "__main__":
    unittest.main()
