import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys

from step_to_acis.probe_runner import (
    build_probe_stages,
    launch_subprocess,
    profile_from_records,
    required_stages_passed,
    run_probe_stage,
    write_probe_report,
)
from step_to_acis.spaceclaim_command import specialize_probe_template


def build_parser():
    parser = argparse.ArgumentParser(
        description="Verify the local SpaceClaim 2022 R2 command-line contract"
    )
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--run-root", type=Path)
    return parser


def default_run_root():
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "StepToAcis" / "probe-runs"
    return Path.cwd() / ".validation" / "probe-runs"


def create_run_directory(root):
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_directory = root.resolve() / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    return run_directory


def main(argv=None):
    arguments = build_parser().parse_args(argv)
    if not arguments.exe.is_file():
        print(
            "SpaceClaim executable does not exist: {}".format(arguments.exe),
            file=sys.stderr,
        )
        return 2
    if arguments.timeout <= 0:
        print("timeout must be greater than zero", file=sys.stderr)
        return 2

    repository_root = Path(__file__).resolve().parents[1]
    template_path = repository_root / "spaceclaim" / "probe_v22.py"
    if not template_path.is_file():
        print("probe template does not exist: {}".format(template_path), file=sys.stderr)
        return 2

    run_directory = create_run_directory(arguments.run_root or default_run_root())
    sentinel_path = run_directory / "sentinel.json"
    specialized_script = run_directory / "probe_v22_specialized.py"
    script_output = run_directory / "script_output.txt"
    specialized_script.write_text(
        specialize_probe_template(
            template_path.read_text(encoding="utf-8"),
            sentinel_path,
        ),
        encoding="utf-8",
    )

    records = []
    for stage in build_probe_stages(arguments.exe, specialized_script, script_output):
        print("Probing {} ...".format(stage.name), flush=True)
        record = run_probe_stage(
            stage,
            sentinel_path,
            arguments.timeout,
            launch_subprocess,
        )
        records.append(record)
        print("  {}: {}".format("PASS" if record.passed else "FAIL", record.reason))
        if stage.required and not record.passed:
            break

    profile = profile_from_records(records)
    report_path = run_directory / "probe_report.json"
    write_probe_report(report_path, arguments.exe, records, profile)
    profile_path = run_directory / "cli_capability_profile.json"
    profile_path.write_text(
        json.dumps(profile.__dict__, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("Probe report: {}".format(report_path))
    return 0 if required_stages_passed(records) else 3


if __name__ == "__main__":
    raise SystemExit(main())
