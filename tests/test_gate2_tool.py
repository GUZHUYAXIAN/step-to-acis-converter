import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class Gate2ToolTests(unittest.TestCase):
    def test_missing_source_is_rejected_before_spaceclaim_launch(self):
        repository_root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(repository_root / "src")
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(repository_root / "tools" / "validate_single_conversion.py"),
                    "--source",
                    str(Path(temporary_directory) / "missing.stp"),
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
        self.assertIn("source STEP does not exist", result.stderr)
