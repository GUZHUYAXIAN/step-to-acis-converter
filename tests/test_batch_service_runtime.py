from pathlib import Path
import json
import tempfile
import unittest

from step_to_acis.batch_service import BatchRequest, NullBatchReporter, run_batch
from step_to_acis.probe_runner import CliCapabilityProfile


class BatchServiceRuntimePathTests(unittest.TestCase):
    def test_request_can_supply_frozen_worker_template(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_dir = root / "input"
            input_dir.mkdir()
            (input_dir / "a.stp").write_bytes(b"STEP")
            executable = root / "SpaceClaim.exe"
            executable.write_bytes(b"fake")
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "spaceclaim_exe": str(executable),
                        "input_dir": str(input_dir),
                        "output_dir": str(root / "output"),
                    }
                ),
                encoding="utf-8",
            )
            frozen_worker = root / "bundle" / "resources" / "worker_v22.py"
            captured = []

            class RecordingSupervisor:
                def __init__(inner_self, **kwargs):
                    captured.append(kwargs["worker_template"])

                def run(inner_self, tasks, preflight, progress_callback):
                    return []

            profile = CliCapabilityProfile(True, True, True, True, False, True, "specialized_worker_literal")
            request = BatchRequest(
                config_path=config_path,
                overrides={},
                capability_profile_path=root / "profile.json",
                worker_template_path=frozen_worker,
            )
            run_batch(
                request,
                NullBatchReporter(),
                capability_profile_loader=lambda *args: profile,
                supervisor_factory=RecordingSupervisor,
            )

        self.assertEqual([frozen_worker], captured)


if __name__ == "__main__":
    unittest.main()
