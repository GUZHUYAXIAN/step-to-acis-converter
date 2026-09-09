from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SpaceClaimCommand:
    executable: Path
    script: Path
    api_version: str = "V22"
    headless: bool = True
    exit_after_script: bool = True
    script_args: str | None = None
    script_output: Path | None = None


@dataclass(frozen=True)
class ProbeObservation:
    returncode: int | None
    timed_out: bool
    sentinel_path: Path
    script_output_path: Path | None = None
    require_script_output: bool = False


@dataclass(frozen=True)
class ProbeEvaluation:
    passed: bool
    reason: str
    sentinel: dict[str, Any] | None = None


def build_command(value: SpaceClaimCommand) -> list[str]:
    arguments = [
        str(value.executable),
        "/RunScript={}".format(value.script),
        "/ScriptAPI={}".format(value.api_version),
    ]
    if value.exit_after_script:
        arguments.append("/ExitAfterScript=True")
    if value.headless:
        arguments.append("/Headless=True")
    if value.script_output is not None:
        arguments.append("/ScriptOutput={}".format(value.script_output))
    if value.script_args is not None:
        arguments.append("/ScriptArgs={}".format(value.script_args))
    return arguments


def build_production_command(
    value: SpaceClaimCommand,
    profile: Any,
) -> list[str]:
    required = (
        ("RunScript", profile.run_script),
        ("ScriptAPI=V22", profile.script_api_v22),
        ("ExitAfterScript", profile.exit_after_script),
        ("Headless", profile.headless),
    )
    missing = [name for name, supported in required if not supported]
    if missing:
        raise ValueError(
            "unproven required SpaceClaim capabilities: {}".format(
                ", ".join(missing)
            )
        )
    if value.script_args is not None and not profile.script_args:
        raise ValueError("ScriptArgs was not proven by the local probe")
    if value.script_output is not None and not profile.script_output:
        raise ValueError("ScriptOutput was not proven by the local probe")
    return build_command(value)


def specialize_probe_template(template: str, sentinel_path: Path) -> str:
    marker = "SENTINEL_PATH = None"
    lines = template.splitlines(keepends=True)
    matching_indexes = [
        index for index, line in enumerate(lines) if line.rstrip("\r\n") == marker
    ]
    if len(matching_indexes) != 1:
        raise ValueError("probe template must contain exactly one sentinel marker")
    replacement = "SENTINEL_PATH = u{}".format(
        json.dumps(str(sentinel_path), ensure_ascii=True)
    )
    index = matching_indexes[0]
    line_ending = lines[index][len(lines[index].rstrip("\r\n")) :]
    lines[index] = replacement + line_ending
    return "".join(lines)


def specialize_worker_template(template: str, manifest_path: Path) -> str:
    marker = "MANIFEST_PATH = None"
    lines = template.splitlines(keepends=True)
    matching_indexes = [
        index for index, line in enumerate(lines) if line.rstrip("\r\n") == marker
    ]
    if len(matching_indexes) != 1:
        raise ValueError("worker template must contain exactly one manifest marker")
    replacement = "MANIFEST_PATH = u{}".format(
        json.dumps(str(manifest_path), ensure_ascii=True)
    )
    index = matching_indexes[0]
    line_ending = lines[index][len(lines[index].rstrip("\r\n")) :]
    lines[index] = replacement + line_ending
    return "".join(lines)


def evaluate_probe_execution(observation: ProbeObservation) -> ProbeEvaluation:
    if observation.timed_out:
        return ProbeEvaluation(False, "process timed out")
    if observation.returncode != 0:
        return ProbeEvaluation(
            False,
            "process exited with exit code {}".format(observation.returncode),
        )
    if not observation.sentinel_path.is_file():
        return ProbeEvaluation(False, "sentinel file is missing")
    try:
        sentinel = json.loads(observation.sentinel_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ProbeEvaluation(False, "sentinel JSON is invalid")
    if not _is_valid_sentinel(sentinel):
        return ProbeEvaluation(False, "sentinel content is invalid")
    if observation.require_script_output:
        output = observation.script_output_path
        if output is None or not output.is_file() or output.stat().st_size <= 0:
            return ProbeEvaluation(False, "script output is missing or empty")
    return ProbeEvaluation(True, "probe passed", sentinel)


def _is_valid_sentinel(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("probe_schema") == 1
        and value.get("script_executed") is True
        and value.get("api_expected") == "V22"
        and value.get("host_api_verified") is True
        and value.get("unicode_round_trip") == "中文 path with spaces"
        and isinstance(value.get("sys_argv"), list)
        and isinstance(value.get("candidate_script_args"), dict)
        and isinstance(value.get("globals_of_interest"), list)
    )
