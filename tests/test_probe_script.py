import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from step_to_acis.spaceclaim_command import specialize_probe_template


class ProbeScriptTests(unittest.TestCase):
    def test_specialized_probe_writes_valid_unicode_sentinel(self):
        repository_root = Path(__file__).resolve().parents[1]
        template_path = repository_root / "spaceclaim" / "probe_v22.py"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            sentinel = root / "中文 folder" / "sentinel.json"
            sentinel.parent.mkdir()
            specialized = root / "probe specialized.py"
            specialized.write_text(
                specialize_probe_template(
                    template_path.read_text(encoding="utf-8"),
                    sentinel,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(specialized), "中文 path with spaces"],
                text=True,
                capture_output=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("SPACECLAIM_V22_PROBE_OUTPUT", result.stdout)
            payload = json.loads(sentinel.read_text(encoding="utf-8"))
            self.assertTrue(payload["script_executed"])
            self.assertEqual("V22", payload["api_expected"])
            self.assertEqual("中文 path with spaces", payload["unicode_round_trip"])
            self.assertIn("中文 path with spaces", payload["sys_argv"])

    def test_host_symbols_can_be_resolved_from_the_script_runtime(self):
        repository_root = Path(__file__).resolve().parents[1]
        template_path = repository_root / "spaceclaim" / "probe_v22.py"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            sentinel = root / "sentinel.json"
            specialized = root / "probe.py"
            specialized.write_text(
                specialize_probe_template(
                    template_path.read_text(encoding="utf-8"),
                    sentinel,
                ),
                encoding="utf-8",
            )
            bootstrap = (
                "import builtins,runpy,sys,types;"
                "builtins.DocumentOpen=type('DocumentOpen',(),{'Execute':object()});"
                "builtins.DocumentSave=type('DocumentSave',(),{'Execute':object()});"
                "builtins.ExportOptions=type('ExportOptions',(),{'Create':object()});"
                "sc=types.ModuleType('SpaceClaim');api=types.ModuleType('SpaceClaim.Api');"
                "v22=types.ModuleType('SpaceClaim.Api.V22');"
                "v22.AcisVersion=type('AcisVersion',(),{'V22':object()});"
                "sys.modules['SpaceClaim']=sc;sys.modules['SpaceClaim.Api']=api;"
                "sys.modules['SpaceClaim.Api.V22']=v22;"
                "runpy.run_path(sys.argv[1],run_name='__main__')"
            )

            result = subprocess.run(
                [sys.executable, "-c", bootstrap, str(specialized)],
                text=True,
                capture_output=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(sentinel.read_text(encoding="utf-8"))
            self.assertTrue(payload["host_api_verified"])
            self.assertEqual(
                {
                    "AcisVersion.V22": True,
                    "DocumentOpen.Execute": True,
                    "DocumentSave.Execute": True,
                    "ExportOptions.Create": True,
                },
                payload["host_api_symbols"],
            )
