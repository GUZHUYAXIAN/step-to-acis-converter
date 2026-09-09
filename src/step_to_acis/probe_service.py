from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import uuid
from typing import Callable

from .capability_cache import (
    CachedCapability,
    cache_path,
    executable_identity,
    save_cached_capability,
)
from .probe_runner import (
    LaunchOutcome,
    build_model_free_headless_stages,
    launch_subprocess,
    profile_from_records,
    required_stages_passed,
    run_probe_stage,
    write_probe_report,
)
from .runtime_paths import RuntimePaths
from .spaceclaim_command import specialize_probe_template
from .spaceclaim_installations import SpaceClaimCandidate


@dataclass(frozen=True)
class ProbeServiceOutcome:
    passed: bool
    profile_path: Path | None
    report_path: Path
    reason: str
    timed_out: bool


def run_model_free_probe(
    candidate: SpaceClaimCandidate,
    paths: RuntimePaths,
    *,
    timeout_seconds: int = 120,
    launcher: Callable[[list[str], int], LaunchOutcome] = launch_subprocess,
) -> ProbeServiceOutcome:
    if candidate.eligibility != "eligible":
        raise ValueError("only an eligible SpaceClaim 2022 R2 candidate may be probed")

    identity = executable_identity(candidate)
    run_directory = paths.probe_runs_root / _run_name()
    run_directory.mkdir(parents=True, exist_ok=False)
    sentinel_path = run_directory / "sentinel.json"
    script_output_path = run_directory / "script-output.txt"
    report_path = run_directory / "probe-report.json"
    specialized_script = run_directory / "probe_v22.py"
    template_path = paths.resource_root / "probe_v22.py"
    specialized_script.write_text(
        specialize_probe_template(
            template_path.read_text(encoding="utf-8"),
            sentinel_path,
        ),
        encoding="utf-8",
        newline="\n",
    )

    records = []
    for stage in build_model_free_headless_stages(
        candidate.executable,
        specialized_script,
        script_output_path,
    ):
        record = run_probe_stage(stage, sentinel_path, timeout_seconds, launcher)
        records.append(record)
        if stage.required and not record.passed:
            break

    profile = profile_from_records(records)
    passed = required_stages_passed(records)
    write_probe_report(report_path, candidate.executable, records, profile)

    profile_path = None
    if passed:
        profile_path = cache_path(paths.capability_profiles_root, identity)
        save_cached_capability(
            profile_path,
            CachedCapability(
                identity=identity,
                profile=profile,
                probe_completed=True,
                probe_report=str(report_path.resolve()),
                verified_at=datetime.now(timezone.utc).isoformat(),
            ),
        )

    failure = next(
        (record for record in records if record.required and not record.passed),
        None,
    )
    return ProbeServiceOutcome(
        passed=passed,
        profile_path=profile_path,
        report_path=report_path,
        reason="probe passed" if failure is None else failure.reason,
        timed_out=any(record.timed_out for record in records),
    )


def _run_name() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return "{}-{}".format(timestamp, uuid.uuid4().hex)
