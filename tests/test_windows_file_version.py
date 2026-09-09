from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from step_to_acis.windows_file_version import (
    FileVersionError,
    FileVersionInfo,
    read_file_version,
)


class WindowsFileVersionTests(unittest.TestCase):
    def test_reads_and_normalizes_product_and_file_versions(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            executable = Path(temporary_directory) / "SpaceClaim.exe"
            executable.write_bytes(b"exe")
            with patch(
                "step_to_acis.windows_file_version._read_version_strings",
                return_value=(" 2022.2.0.0\x00", "2022.2.45056.55939 "),
            ):
                info = read_file_version(executable)

        self.assertEqual(FileVersionInfo("2022.2.0.0", "2022.2.45056.55939"), info)

    def test_missing_executable_fails_before_windows_api(self):
        with self.assertRaisesRegex(FileVersionError, "does not exist"):
            read_file_version(Path("missing-SpaceClaim.exe"))

    def test_missing_or_malformed_metadata_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            executable = Path(temporary_directory) / "SpaceClaim.exe"
            executable.write_bytes(b"exe")
            for values in [("", "2022.2.1.0"), ("2022.2", "2022.2.1.0")]:
                with self.subTest(values=values), patch(
                    "step_to_acis.windows_file_version._read_version_strings",
                    return_value=values,
                ):
                    with self.assertRaises(FileVersionError):
                        read_file_version(executable)

    def test_windows_api_failure_is_classified(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            executable = Path(temporary_directory) / "SpaceClaim.exe"
            executable.write_bytes(b"exe")
            with patch(
                "step_to_acis.windows_file_version._read_version_strings",
                side_effect=OSError("version resource denied"),
            ):
                with self.assertRaisesRegex(FileVersionError, "version resource denied"):
                    read_file_version(executable)


if __name__ == "__main__":
    unittest.main()
