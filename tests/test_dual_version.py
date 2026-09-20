from dataclasses import replace
import json
from pathlib import Path
import re
import runpy
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from step_to_acis.batch_service import BatchRequest, NullBatchReporter, run_batch
from step_to_acis.capability_cache import CachedCapability, executable_identity, load_cached_capability, save_cached_capability
from step_to_acis.gui import ConverterGui
from step_to_acis.gui_models import GuiFormValues
from step_to_acis.gui_settings import save_gui_settings
from step_to_acis.portable_config import portable_config_payload
from step_to_acis.probe_runner import CliCapabilityProfile, LaunchOutcome, required_stages_passed
from step_to_acis.probe_service import run_model_free_probe
from step_to_acis.runtime_paths import RuntimePaths, resource_path
from step_to_acis.spaceclaim_command import SpaceClaimCommand, build_production_command, specialize_probe_template, specialize_worker_template
from step_to_acis.spaceclaim_installations import candidate_paths, classify_candidate
from step_to_acis.spaceclaim_versions import release_for_api, validate_acis_version
from step_to_acis.windows_file_version import FileVersionInfo
from step_to_acis.environment_controller import _preferred_eligible
from step_to_acis.environment_models import CheckResult, EnvironmentState, REQUIRED_CHECK_IDS
from step_to_acis.portable_main import launch_converter
import tests.test_gui as gui_fakes
import tests.test_worker_source as worker_fakes
from step_to_acis.models import ConversionTask, OutputFormat
from step_to_acis.protocol import write_manifest, read_complete_events


def profile_261():
    return CliCapabilityProfile(True, False, True, True, False, True,
                                "specialized_worker_literal", "V261", True)


class DualVersionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.exe = self.root / "custom-install" / "v261" / "SCDM" / "SpaceClaim.exe"
        self.exe.parent.mkdir(parents=True)
        self.exe.write_bytes(b"test executable")
        self.candidate = classify_candidate(self.exe, version_reader=lambda p: FileVersionInfo("2026.1.0.0", "2026.1.53248.53377"))
        self.resources = Path(__file__).resolve().parents[1] / "spaceclaim"
        self.paths = RuntimePaths(self.resources, self.root, self.root / "environment",
                                  self.root / "profiles", self.root / "probes", self.root / "gui.json")

    def test_new_environment_variable_and_metadata_eligibility(self):
        paths = candidate_paths(environ={"AWP_ROOT261": str(self.exe.parents[1])}, drive_roots=(), registry_values=(), previous=None)
        self.assertEqual(self.exe.resolve(), paths[0][0])
        self.assertEqual("eligible", self.candidate.eligibility)
        self.assertEqual("V261", self.candidate.release.api_version)

    def test_coexisting_versions_prefer_saved_choice_then_newest(self):
        old = replace(self.candidate, executable=self.root/'v222'/'SCDM'/'SpaceClaim.exe',
                      product_version='2022.2.0.0', file_version='2022.2.1.0', layout_version='v222')
        candidates = (old, self.candidate)
        self.assertEqual(self.candidate, _preferred_eligible(candidates, None))
        self.assertEqual(old, _preferred_eligible(candidates, old.executable))
        self.assertEqual(self.candidate, _preferred_eligible(candidates, self.root/'deleted.exe'))

    def test_portable_launch_uses_new_worker_config_and_form(self):
        captured = {}
        checks = tuple(CheckResult(k, 'required', 'pass', 'ok', 'ok', '') for k in REQUIRED_CHECK_IDS)
        state = EnvironmentState((self.candidate,), self.candidate, checks, self.root/'profile.json')
        launch_converter(gui_fakes.FakeRoot(), state, self.paths,
                         converter_factory=lambda root, **kw: captured.update(kw))
        self.assertEqual('V261', captured['api_version'])
        self.assertEqual('V5', captured['defaults'].acis_version)
        self.assertEqual('worker_v261.py', captured['worker_template_path'].name)
        self.assertEqual('V5', json.loads(captured['config_path'].read_text(encoding='utf-8'))['acis_version'])

    def test_cross_version_layout_and_metadata_are_rejected(self):
        for product, file in [("2022.2.0.0", "2022.2.1.0"), ("2026.1.0.0", "2022.2.1.0"), ("2026.2.0.0", "2026.2.1.0")]:
            with self.subTest(product=product, file=file):
                self.assertEqual("unsupported", classify_candidate(self.exe, version_reader=lambda p: FileVersionInfo(product, file)).eligibility)

    def test_acis_contracts_are_not_interchangeable(self):
        validate_acis_version("V261", "V5")
        validate_acis_version("V22", "V22")
        for api, acis in [("V261", "V22"), ("V22", "V5"), ("V999", "V5")]:
            with self.assertRaises(ValueError):
                validate_acis_version(api, acis)
        self.assertEqual("V5", portable_config_payload(self.exe, "V261")["acis_version"])
        self.assertEqual("V22", portable_config_payload(self.exe)["acis_version"])

    def test_command_requires_matching_api_proof(self):
        new = SpaceClaimCommand(self.exe, Path("worker.py"), api_version="V261")
        self.assertIn("/ScriptAPI=V261", build_production_command(new, profile_261()))
        for profile in [replace(profile_261(), api_version="V22"), replace(profile_261(), script_api_v261=False), replace(profile_261(), script_api_v22=True)]:
            with self.assertRaises(ValueError):
                build_production_command(new, profile)
        with self.assertRaises(ValueError):
            build_production_command(replace(new, api_version="V22"), profile_261())

    def test_version_bound_cache_and_legacy_schema(self):
        identity = executable_identity(self.candidate)
        path = self.root / "cache.json"
        value = CachedCapability(identity, profile_261(), True, "report.json", "now")
        save_cached_capability(path, value)
        self.assertEqual(value, load_cached_capability(path, identity))
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["cache_schema"] = 2
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertIsNone(load_cached_capability(path, identity))
        save_cached_capability(path, replace(value, profile=replace(profile_261(), api_version="V22", script_api_v261=False, script_api_v22=True)))
        self.assertIsNone(load_cached_capability(path, identity))

    def test_old_schema_two_cache_remains_valid_only_for_old_host(self):
        old = replace(self.candidate, product_version="2022.2.0.0", file_version="2022.2.1.0", layout_version="v222")
        identity = executable_identity(old)
        profile = CliCapabilityProfile(True, True, True, True, False, True, "specialized_worker_literal")
        path = self.root / "old.json"
        save_cached_capability(path, CachedCapability(identity, profile, True, "old-report", "now"))
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["cache_schema"] = 2
        del payload["capabilities"]["api_version"]
        del payload["capabilities"]["script_api_v261"]
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(profile, load_cached_capability(path, identity).profile)

    def launcher(self, command, timeout, api="V261"):
        self.assertIn("/ScriptAPI=V261", command)
        self.assertIn("/Headless=True", command)
        script = Path(next(s.split("=", 1)[1] for s in command if s.startswith("/RunScript=")))
        self.assertEqual("probe_v261.py", script.name)
        marker = re.search(r"^SENTINEL_PATH = u(.+)$", script.read_text(encoding="utf-8"), re.M)
        Path(json.loads(marker.group(1))).write_text(json.dumps({
            "probe_schema": 1, "script_executed": True, "api_expected": api,
            "host_api_verified": True, "unicode_round_trip": "中文 path with spaces",
            "sys_argv": [], "candidate_script_args": {}, "globals_of_interest": [],
        }), encoding="utf-8")
        for item in command:
            if item.startswith("/ScriptOutput="):
                Path(item.split("=", 1)[1]).write_text("output", encoding="utf-8")
        return LaunchOutcome(0, False, "", "", "start", "end", 0.1)

    def test_new_probe_writes_new_api_cache(self):
        result = run_model_free_probe(self.candidate, self.paths, launcher=self.launcher)
        self.assertTrue(result.passed)
        cached = load_cached_capability(result.profile_path, executable_identity(self.candidate))
        self.assertTrue(cached.profile.supports_api("V261"))
        self.assertFalse(cached.profile.supports_api("V22"))
        self.assertEqual([], list(self.root.rglob("*.sab")))

    def test_actual_probe_script_fails_closed_without_cad_symbols(self):
        sentinel = self.root/'sentinel.json'
        script = self.root/'probe.py'
        script.write_text(specialize_probe_template(resource_path('probe_v261.py').read_text(encoding='utf-8'), sentinel), encoding='utf-8')
        runpy.run_path(str(script))
        payload = json.loads(sentinel.read_text(encoding='utf-8'))
        self.assertEqual('V261', payload['api_expected'])
        self.assertFalse(payload['host_api_verified'])

    def test_actual_probe_script_verifies_api_without_opening_a_model(self):
        api = types.ModuleType('SpaceClaim.Api.V261')
        commands = types.ModuleType('SpaceClaim.Api.V261.Scripting.Commands')
        api.AcisUnits = types.SimpleNamespace(Millimeters='mm')
        api.ExportOptions = types.SimpleNamespace(Create=lambda: types.SimpleNamespace(Acis=types.SimpleNamespace(Units=None)))
        api.Window = types.SimpleNamespace(Close=lambda: self.fail('probe closed document'))
        commands.DocumentOpen = types.SimpleNamespace(Execute=lambda *args: self.fail('probe opened model'))
        commands.DocumentSave = types.SimpleNamespace(Execute=lambda *args: self.fail('probe saved model'))
        modules = {name: types.ModuleType(name) for name in ['SpaceClaim', 'SpaceClaim.Api', 'SpaceClaim.Api.V261.Scripting']}
        modules.update({'SpaceClaim.Api.V261':api, 'SpaceClaim.Api.V261.Scripting.Commands':commands})
        sentinel = self.root/'sentinel.json'
        script = self.root/'probe.py'
        script.write_text(specialize_probe_template(resource_path('probe_v261.py').read_text(encoding='utf-8'), sentinel), encoding='utf-8')
        with patch.dict(sys.modules, modules):
            runpy.run_path(str(script))
        self.assertTrue(json.loads(sentinel.read_text(encoding='utf-8'))['host_api_verified'])

    def test_probe_rejects_stale_v22_sentinel_and_no_required_records(self):
        result = run_model_free_probe(self.candidate, self.paths, launcher=lambda c, t: self.launcher(c, t, api="V22"))
        self.assertFalse(result.passed)
        self.assertIsNone(result.profile_path)
        self.assertFalse(required_stages_passed([]))

    def test_gui_changes_unsupported_saved_version_visibly_without_saving(self):
        settings = self.root / "gui-settings.json"
        old = GuiFormValues("input", "output", acis_version="V22")
        save_gui_settings(settings, old)
        before = settings.read_bytes()
        class View(gui_fakes.FakeView):
            def configure_release(self, release, changed):
                self.release_notice = (release.output_note, changed)
        gui = ConverterGui(gui_fakes.FakeRoot(), config_path=self.root / "config.json", capability_profile_path=self.root / "cache.json",
                           settings_path=settings, defaults=GuiFormValues("", "", acis_version="V5"), view_factory=View, api_version="V261")
        self.assertEqual("V5", gui.view.values.acis_version)
        self.assertTrue(gui.view.release_notice[1])
        self.assertIn("5.0", gui.view.release_notice[0])
        self.assertEqual(before, settings.read_bytes())

    def test_batch_selects_new_worker_and_rejects_v22_before_launch(self):
        input_dir = self.root / "input"
        input_dir.mkdir()
        (input_dir / "model.step").write_bytes(b"test")
        config = self.root / "config.json"
        captured = []
        class Supervisor:
            def __init__(self, **kw):
                captured.append((kw["worker_template"], kw["command_factory"](Path("w.py"), Path("s.txt"))))
            def run(self, tasks, preflight, callback):
                return []
        for version in ("V5", "V22"):
            config.write_text(json.dumps({"spaceclaim_exe": str(self.exe), "input_dir": str(input_dir), "output_dir": str(self.root/version), "acis_version": version}), encoding="utf-8")
            outcome = run_batch(BatchRequest(config, {}, self.root/"profile"), NullBatchReporter(), capability_profile_loader=lambda *args: profile_261(), supervisor_factory=Supervisor)
            self.assertEqual(version == "V5", outcome.exit_code == 0)
        self.assertEqual(1, len(captured))
        self.assertEqual("worker_v261.py", captured[0][0].name)
        self.assertIn("/ScriptAPI=V261", captured[0][1])


class V261WorkerTests(unittest.TestCase):
    def run_worker(self, version="V5", bad_header=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        runtime = worker_fakes.FakeSpaceClaimRuntime()
        runtime.install()
        self.addCleanup(runtime.uninstall)
        old = sys.modules['SpaceClaim.Api.V22']
        commands = sys.modules['SpaceClaim.Api.V22.Scripting.Commands']
        new = types.ModuleType('SpaceClaim.Api.V261')
        class AcisOptions:
            __slots__ = ('Units',)
        class ExportOptions:
            @staticmethod
            def Create():
                options = types.SimpleNamespace(Acis=AcisOptions())
                runtime.options.append(options)
                return options
        new.AcisUnits, new.Window, new.ExportOptions = old.AcisUnits, old.Window, ExportOptions
        original_save = commands.DocumentSave.Execute
        def save(path, options):
            original_save(path, options)
            if bad_header:
                Path(path).write_bytes(b'2200 wrong version')
            elif str(path).endswith('.sat'):
                Path(path).write_bytes(b'500 0 1 0\nsynthetic fake SAT')
            else:
                Path(path).write_bytes(b'ACIS BinaryFile' + struct.pack('<I', 500) + b'fake')
        commands.DocumentSave.Execute = save
        aliases = {'SpaceClaim.Api.V261': new, 'SpaceClaim.Api.V261.Scripting': types.ModuleType('SpaceClaim.Api.V261.Scripting'), 'SpaceClaim.Api.V261.Scripting.Commands': commands}
        patcher = patch.dict(sys.modules, aliases)
        patcher.start()
        self.addCleanup(patcher.stop)
        source = root / 'source.step'
        source.write_bytes(b'unchanged STEP')
        tasks = [ConversionTask(i, 't'+str(i), source, root/('out'+fmt.extension), root/('temp'+fmt.extension), fmt, source.stat().st_size) for i, fmt in enumerate((OutputFormat.SAB, OutputFormat.SAT), 1)]
        manifest, events = root/'manifest.json', root/'events.jsonl'
        write_manifest(manifest, 'run', 'chunk', {'acis_version':version, 'acis_units':'Millimeters', 'heartbeat_interval_seconds':60}, tasks, events)
        worker = root/'worker.py'
        worker.write_text(specialize_worker_template(resource_path('worker_v261.py').read_text(encoding='utf-8'), manifest), encoding='utf-8')
        runpy.run_path(str(worker))
        self.assertEqual(b'unchanged STEP', source.read_bytes())
        return runtime, [e for e in read_complete_events(events).events if e['event']=='task_finished']

    def test_exports_both_formats_without_accessing_removed_version_property(self):
        runtime, results = self.run_worker()
        self.assertEqual(['Success', 'Success'], [r['status'] for r in results])
        self.assertEqual(2, runtime.closed)
        self.assertTrue(all(o.Acis.Units == 'ENUM-MM' for o in runtime.options))

    def test_unsupported_version_never_opens_or_saves_model(self):
        runtime, results = self.run_worker(version='V22')
        self.assertEqual([], runtime.opened)
        self.assertEqual([], runtime.saved)
        self.assertTrue(all(r['status']=='Failed' for r in results))

    def test_nonempty_wrong_version_output_is_rejected(self):
        runtime, results = self.run_worker(bad_header=True)
        self.assertTrue(all(r['status']=='Failed' for r in results))
        self.assertTrue(all('version' in r['error_message'] for r in results))


if __name__ == '__main__':
    unittest.main()
