import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.probe_spaceclaim import build_parser, create_run_directory


class ProbeToolTests(unittest.TestCase):
    def test_spaceclaim_executable_must_be_selected_explicitly(self):
        with self.assertRaises(SystemExit) as error:
            build_parser().parse_args([])

        self.assertEqual(2, error.exception.code)

    def test_run_directory_is_absolute_even_when_root_is_relative(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            previous = Path.cwd()
            os.chdir(temporary_directory)
            try:
                run_directory = create_run_directory(Path("relative-root"))
            finally:
                os.chdir(previous)

        self.assertTrue(run_directory.is_absolute())

    def test_missing_spaceclaim_executable_is_a_preflight_error(self):
        repository_root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(repository_root / "src")
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(repository_root / "tools" / "probe_spaceclaim.py"),
                    "--exe",
                    str(Path(temporary_directory) / "missing.exe"),
                    "--run-root",
                    temporary_directory,
                ],
                cwd=repository_root,
                env=environment,
                text=True,
                encoding="utf-8",
                capture_output=True,
            )

        self.assertEqual(2, result.returncode)
        self.assertIn("does not exist", result.stderr)
