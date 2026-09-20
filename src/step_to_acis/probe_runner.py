from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
import locale
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Callable, Sequence

from .spaceclaim_command import (
    ProbeObservation,
    SpaceClaimCommand,
    build_command,
    evaluate_probe_execution,
)


SCRIPT_ARG_SENTINEL = "中文 path with spaces"


@dataclass(frozen=True)
class ProbeStage:
    name: str
    required: bool
    command: SpaceClaimCommand
    require_script_output: bool = False


@dataclass(frozen=True)
class ProbeStageRecord:
    name: str
    required: bool
    passed: bool
    reason: str
    command: tuple[str, ...] = ()
    returncode: int | None = None
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""
    started_at: str = ""
    ended_at: str = ""
    elapsed_seconds: float = 0.0
    sentinel: dict[str, Any] | None = None
    script_arg_exposure: str | None = None


@dataclass(frozen=True)
class LaunchOutcome:
    returncode: int | None
    timed_out: bool
    stdout: str
    stderr: str
    started_at: str
    ended_at: str
    elapsed_seconds: float


@dataclass(frozen=True)
class CliCapabilityProfile:
    run_script: bool
    script_api_v22: bool
    exit_after_script: bool
    headless: bool
    script_args: bool
    script_output: bool
    script_args_strategy: str
    api_version: str = "V22"
    script_api_v261: bool = False

    def supports_api(self, api_version: str) -> bool:
        if self.api_version != api_version:
            return False
        return ((api_version == "V22" and self.script_api_v22 is True and not self.script_api_v261)
                or (api_version == "V261" and self.script_api_v261 is True and not self.script_api_v22))


def build_probe_stages(
    executable: Path,
    script: Path,
    script_output: Path,
) -> list[ProbeStage]:
    return [
        ProbeStage(
            "required_base",
            True,
            SpaceClaimCommand(executable=executable, script=script, headless=False),
        ),
        ProbeStage(
            "required_headless",
            True,
            SpaceClaimCommand(executable=executable, script=script),
        ),
        ProbeStage(
            "optional_script_output",
            False,
            SpaceClaimCommand(
                executable=executable,
                script=script,
                script_output=script_output,
            ),
            require_script_output=True,
        ),
        ProbeStage(
            "optional_script_args",
            False,
            SpaceClaimCommand(
                executable=executable,
                script=script,
                script_args=SCRIPT_ARG_SENTINEL,
            ),
        ),
    ]


def build_model_free_headless_stages(
    executable: Path,
    script: Path,
    script_output: Path,
    api_version: str = "V22",
) -> list[ProbeStage]:
    """Build the portable-release probe without ever opening the SpaceClaim UI."""
    from .spaceclaim_versions import release_for_api
    release_for_api(api_version)
    stages = [
        ProbeStage(
            "required_headless",
            True,
            SpaceClaimCommand(executable=executable, script=script),
        ),
        ProbeStage(
            "optional_script_output",
            False,
            SpaceClaimCommand(
                executable=executable,
                script=script,
                script_output=script_output,
            ),
            require_script_output=True,
        ),
        ProbeStage(
            "optional_script_args",
            False,
            SpaceClaimCommand(
                executable=executable,
                script=script,
                script_args=SCRIPT_ARG_SENTINEL,
            ),
        ),
    ]
    return [replace(stage, command=replace(stage.command, api_version=api_version)) for stage in stages]


def required_stages_passed(records: Sequence[ProbeStageRecord]) -> bool:
    required = [record for record in records if record.required]
    return bool(required) and all(record.passed for record in required)


def find_script_arg_exposure(
    sentinel: dict[str, Any],
    expected_value: str,
) -> str | None:
    for index, value in enumerate(sentinel.get("sys_argv", [])):
        if value == expected_value:
            return "sys.argv[{}]".format(index)
    for name, value in sorted(sentinel.get("candidate_script_args", {}).items()):
        if value == expected_value:
            return "global:{}".format(name)
    return None


def run_probe_stage(
    stage: ProbeStage,
    sentinel_path: Path,
    timeout_seconds: int,
    launcher: Callable[[list[str], int], LaunchOutcome],
) -> ProbeStageRecord:
    sentinel_path.unlink(missing_ok=True)
    if stage.command.script_output is not None:
        stage.command.script_output.unlink(missing_ok=True)
    command = build_command(stage.command)
    outcome = launcher(command, timeout_seconds)
    evaluation = evaluate_probe_execution(
        ProbeObservation(
            returncode=outcome.returncode,
            timed_out=outcome.timed_out,
            sentinel_path=sentinel_path,
            script_output_path=stage.command.script_output,
            require_script_output=stage.require_script_output,
            api_version=stage.command.api_version,
        )
    )
    passed = evaluation.passed
    reason = evaluation.reason
    exposure = None
    if passed and stage.name == "optional_script_args":
        exposure = find_script_arg_exposure(
            evaluation.sentinel or {},
            stage.command.script_args or "",
        )
        if exposure is None:
            passed = False
            reason = "ScriptArgs value was not exposed to the script"
    return ProbeStageRecord(
        name=stage.name,
        required=stage.required,
        passed=passed,
        reason=reason,
        command=tuple(command),
        returncode=outcome.returncode,
        timed_out=outcome.timed_out,
        stdout=outcome.stdout,
        stderr=outcome.stderr,
        started_at=outcome.started_at,
        ended_at=outcome.ended_at,
        elapsed_seconds=outcome.elapsed_seconds,
        sentinel=evaluation.sentinel,
        script_arg_exposure=exposure,
    )


def launch_subprocess(command: list[str], timeout_seconds: float) -> LaunchOutcome:
    started_at = datetime.now(timezone.utc)
    started_counter = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            timeout=timeout_seconds,
            check=False,
        )
        returncode = completed.returncode
        timed_out = False
        stdout = _decode_process_output(completed.stdout)
        stderr = _decode_process_output(completed.stderr)
    except subprocess.TimeoutExpired as error:
        returncode = None
        timed_out = True
        stdout = _decode_process_output(error.stdout)
        captured_stderr = _decode_process_output(error.stderr)
        stderr = "process timed out after {} seconds".format(timeout_seconds)
        if captured_stderr:
            stderr += "\n" + captured_stderr
    ended_at = datetime.now(timezone.utc)
    return LaunchOutcome(
        returncode=returncode,
        timed_out=timed_out,
        stdout=stdout,
        stderr=stderr,
        started_at=started_at.isoformat(),
        ended_at=ended_at.isoformat(),
        elapsed_seconds=time.perf_counter() - started_counter,
    )


def profile_from_records(records: Sequence[ProbeStageRecord], api_version: str = "V22") -> CliCapabilityProfile:
    by_name = {record.name: record for record in records}
    base = by_name.get("required_base")
    headless = by_name.get("required_headless")
    script_args = by_name.get("optional_script_args")
    script_output = by_name.get("optional_script_output")
    # The portable self-check intentionally has no visible/non-headless base
    # stage. A passing required Headless stage proves the same required command
    # switches while satisfying the release's model-free startup contract.
    base_passed = bool(base.passed if base is not None else headless and headless.passed)
    # Real records must attest the requested API. Legacy synthetic test records
    # without a sentinel remain supported for V22 only.
    required = [record for record in records if record.required and record.passed]
    if api_version not in {"V22", "V261"} or any(
        (record.sentinel or {}).get("api_expected", "V22") != api_version for record in required
    ):
        base_passed = False
    args_passed = bool(script_args and script_args.passed)
    return CliCapabilityProfile(
        run_script=base_passed,
        script_api_v22=base_passed and api_version == "V22",
        exit_after_script=base_passed,
        headless=bool(headless and headless.passed),
        script_args=args_passed,
        script_output=bool(script_output and script_output.passed),
        script_args_strategy=(
            script_args.script_arg_exposure
            if args_passed and script_args is not None
            else "specialized_worker_literal"
        ),
        api_version=api_version,
        script_api_v261=base_passed and api_version == "V261",
    )


def _decode_process_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    getencoding = getattr(locale, "getencoding", None)
    encoding = getencoding() if getencoding is not None else locale.getpreferredencoding(False)
    return value.decode(encoding, errors="replace")


def write_probe_report(
    path: Path,
    executable: Path,
    records: Sequence[ProbeStageRecord],
    profile: CliCapabilityProfile,
) -> None:
    payload = {
        "probe_report_schema": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "spaceclaim_executable": str(executable),
        "required_stages_passed": required_stages_passed(records),
        "profile": asdict(profile),
        "stages": [asdict(record) for record in records],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary_path, path)
