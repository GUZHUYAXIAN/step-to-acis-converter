from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from step_to_acis.portable_config import (
    has_accepted_portable_paths,
    mark_portable_paths_accepted,
    portable_config_payload,
    write_portable_config,
)


class PortableConfigTests(unittest.TestCase):
    def test_payload_has_blank_business_paths_and_safe_defaults(self):
        payload = portable_config_payload(
            Path(r"C:\Program Files\ANSYS Inc\v222\SCDM\SpaceClaim.exe")
        )

        self.assertEqual("", payload["input_dir"])
        self.assertEqual("", payload["output_dir"])
        self.assertEqual(["SAB"], payload["output_formats"])
        self.assertEqual("Skip", payload["overwrite_policy"])
        self.assertEqual("V22", payload["acis_version"])
        self.assertEqual("Millimeters", payload["acis_units"])
        self.assertEqual(20, payload["chunk_size"])
        self.assertEqual(900, payload["heartbeat_timeout_seconds"])
        self.assertEqual(0, payload["retry_count"])

    def test_runtime_config_is_written_atomically(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state" / "runtime_config.json"
            with patch("step_to_acis.portable_config.os.replace", wraps=__import__("os").replace) as replace_spy:
                write_portable_config(path, Path(r"C:\Program Files\ANSYS Inc\v222\SCDM\SpaceClaim.exe"))

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("", payload["input_dir"])
            self.assertEqual(path.with_name(path.name + ".tmp"), replace_spy.call_args.args[0])
            self.assertFalse(path.with_name(path.name + ".tmp").exists())

    def test_path_acceptance_marker_is_fail_closed_and_atomic(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            marker = Path(temporary_directory) / "nested" / "portable_paths.json"
            self.assertFalse(has_accepted_portable_paths(marker))
            marker.parent.mkdir(parents=True)
            marker.write_text("{broken", encoding="utf-8")
            self.assertFalse(has_accepted_portable_paths(marker))

            mark_portable_paths_accepted(marker)

            self.assertTrue(has_accepted_portable_paths(marker))
            self.assertEqual(1, json.loads(marker.read_text(encoding="utf-8"))["schema"])
            self.assertFalse(marker.with_name(marker.name + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
