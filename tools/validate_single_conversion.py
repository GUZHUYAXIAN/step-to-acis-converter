import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

from step_to_acis.models import ConversionTask, OutputFormat
from step_to_acis.probe_runner import CliCapabilityProfile, launch_subprocess
from step_to_acis.protocol import read_complete_events, write_manifest
from step_to_acis.spaceclaim_command import (
    SpaceClaimCommand,
    build_production_command,
    specialize_worker_template,
)


def build_parser():
    parser = argparse.ArgumentParser(description="Run the Gate 2 one-file conversion")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--run-root", type=Path, default=Path(".validation/gate2"))
    parser.add_argument("--format", choices=["SAB", "SAT"], default="SAB")
    parser.add_argument("--timeout", type=float, default=300.0)
    return parser


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        while True:
            block = source_file.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest().upper()


def create_run_directory(root):
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = root.resolve() / run_id
    path.mkdir(parents=True, exist_ok=False)
    return run_id, path


def main(argv=None):
    arguments = build_parser().parse_args(argv)
    source = arguments.source.resolve()
    if not source.is_file() or source.suffix.lower() not in (".stp", ".step"):
        print("source STEP does not exist: {}".format(source), file=sys.stderr)
        return 2
    if arguments.timeout <= 0:
        print("timeout must be greater than zero", file=sys.stderr)
        return 2

    repository_root = Path(__file__).resolve().parents[1]
    profile_payload = json.loads(
        (repository_root / "spaceclaim_cli_profile.json").read_text(encoding="utf-8")
    )
    profile = CliCapabilityProfile(**profile_payload["capabilities"])
    executable = Path(profile_payload["spaceclaim_executable"])
    if not executable.is_file():
        print("verified SpaceClaim executable is missing: {}".format(executable), file=sys.stderr)
        return 2
    if sha256_file(executable) != profile_payload["spaceclaim_executable_sha256"]:
        print("SpaceClaim executable hash differs from the verified profile", file=sys.stderr)
        return 3

    run_id, run_directory = create_run_directory(arguments.run_root)
    output_format = OutputFormat(arguments.format)
    output = run_directory / (source.stem + output_format.extension)
    staging = run_directory / ("." + source.stem + ".gate2.partial" + output_format.extension)
    task = ConversionTask(
        sequence=1,
        task_id="gate2-task-1",
        source_path=source,
        output_path=output,
        staging_output_path=staging,
        output_format=output_format,
        source_size_bytes=source.stat().st_size,
    )
    events_path = run_directory / "events.jsonl"
    manifest_path = run_directory / "manifest.json"
    write_manifest(
        manifest_path,
        run_id,
        "gate2-chunk-1",
        {
            "acis_version": "V22",
            "acis_units": "Millimeters",
            "heartbeat_interval_seconds": 5,
        },
        [task],
        events_path,
    )
    worker_template = repository_root / "spaceclaim" / "worker_v22.py"
    worker = run_directory / "worker_v22_specialized.py"
    worker.write_text(
        specialize_worker_template(
            worker_template.read_text(encoding="utf-8"),
            manifest_path,
        ),
        encoding="utf-8",
    )
    script_output = run_directory / "spaceclaim_script_output.txt"
    command = build_production_command(
        SpaceClaimCommand(
            executable=executable,
            script=worker,
            script_output=script_output,
        ),
        profile,
    )
    before = {
        "size_bytes": source.stat().st_size,
        "mtime_ns": source.stat().st_mtime_ns,
        "sha256": sha256_file(source),
    }
    launch = launch_subprocess(command, arguments.timeout)
    protocol_error = ""
    try:
        event_result = read_complete_events(events_path)
        events = list(event_result.events)
        diagnostics = list(event_result.diagnostics)
    except Exception as error:
        events = []
        diagnostics = []
        protocol_error = str(error)

    terminal = [
        event
        for event in events
        if event.get("event") == "task_finished"
        and event.get("task_id") == task.task_id
    ]
    fatal_events = [event for event in events if event.get("event") == "worker_fatal"]
    worker_finished = any(event.get("event") == "worker_finished" for event in events)
    finalization_error = ""
    if (
        len(terminal) == 1
        and terminal[0].get("status") == "Success"
        and not fatal_events
        and worker_finished
        and staging.is_file()
        and staging.stat().st_size > 0
    ):
        os.replace(staging, output)
    else:
        finalization_error = "worker did not produce one clean successful terminal result"

    after = {
        "size_bytes": source.stat().st_size,
        "mtime_ns": source.stat().st_mtime_ns,
        "sha256": sha256_file(source),
    }
    source_unchanged = before == after
    passed = (
        launch.returncode == 0
        and not launch.timed_out
        and not protocol_error
        and not finalization_error
        and source_unchanged
        and output.is_file()
        and output.stat().st_size > 0
    )
    report = {
        "gate2_report_schema": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "source": str(source),
        "source_before": before,
        "source_after": after,
        "source_unchanged": source_unchanged,
        "output": str(output),
        "output_size_bytes": output.stat().st_size if output.is_file() else 0,
        "worker_sha256": sha256_file(worker),
        "command": command,
        "launch": asdict(launch),
        "events": events,
        "diagnostics": diagnostics,
        "protocol_error": protocol_error,
        "finalization_error": finalization_error,
    }
    report_path = run_directory / "gate2_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("Gate 2 report: {}".format(report_path))
    print("Gate 2 result: {}".format("PASS" if passed else "FAIL"))
    return 0 if passed else 4


if __name__ == "__main__":
    raise SystemExit(main())
