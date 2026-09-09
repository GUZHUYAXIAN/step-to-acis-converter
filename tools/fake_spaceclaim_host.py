from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys


FAKE_ACIS_BYTES = b"FAKE-ACIS-VALIDATION"


class FakeHostError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedArguments:
    script: Path
    script_output: Path | None


def parse_arguments(arguments: list[str]) -> ParsedArguments:
    values = {}
    for argument in arguments:
        if not argument.startswith("/") or "=" not in argument:
            raise FakeHostError("unsupported argument: {}".format(argument))
        name, value = argument[1:].split("=", 1)
        if name in values:
            raise FakeHostError("duplicate argument: {}".format(name))
        values[name] = value
    required = {
        "RunScript",
        "ScriptAPI",
        "ExitAfterScript",
        "Headless",
    }
    if not required.issubset(values):
        raise FakeHostError("required Headless arguments are missing")
    if values["ScriptAPI"] != "V22":
        raise FakeHostError("only ScriptAPI V22 is accepted")
    for name in ("ExitAfterScript", "Headless"):
        if values[name].casefold() != "true":
            raise FakeHostError("{} must be true".format(name))
    allowed = required | {"ScriptOutput", "ScriptArgs"}
    unknown = set(values) - allowed
    if unknown:
        raise FakeHostError("unsupported argument: {}".format(sorted(unknown)[0]))
    return ParsedArguments(
        Path(values["RunScript"]),
        Path(values["ScriptOutput"]) if "ScriptOutput" in values else None,
    )


def extract_specialized_path(source: str, marker: str) -> Path:
    pattern = r"^{} = u(.+)$".format(re.escape(marker))
    matches = re.findall(pattern, source, flags=re.MULTILINE)
    if len(matches) != 1:
        raise FakeHostError("{} must occur exactly once".format(marker))
    try:
        value = json.loads(matches[0])
    except json.JSONDecodeError as error:
        raise FakeHostError("{} value is invalid".format(marker)) from error
    if not isinstance(value, str) or not value:
        raise FakeHostError("{} path is invalid".format(marker))
    return Path(value)


def run_script(script_path: Path, script_output: Path | None) -> int:
    source = script_path.read_text(encoding="utf-8")
    sentinel_count = source.count("SENTINEL_PATH = u")
    manifest_count = source.count("MANIFEST_PATH = u")
    if sentinel_count and not manifest_count:
        result = _run_probe(extract_specialized_path(source, "SENTINEL_PATH"))
    elif manifest_count and not sentinel_count:
        result = _run_worker(extract_specialized_path(source, "MANIFEST_PATH"))
    else:
        raise FakeHostError("script must contain exactly one supported marker")
    if script_output is not None:
        script_output.parent.mkdir(parents=True, exist_ok=True)
        script_output.write_text("FAKE_SPACECLAIM_SCRIPT_OUTPUT\n", encoding="utf-8")
    return result


def _run_probe(sentinel_path: Path) -> int:
    sentinel_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "probe_schema": 1,
        "script_executed": True,
        "api_expected": "V22",
        "host_api_verified": True,
        "host_api_symbols": {
            "DocumentOpen.Execute": True,
            "DocumentSave.Execute": True,
            "ExportOptions.Create": True,
            "AcisVersion.V22": True,
        },
        "process_id": os.getpid(),
        "sys_argv": [],
        "candidate_script_args": {},
        "globals_of_interest": [],
        "unicode_round_trip": "中文 path with spaces",
    }
    sentinel_path.write_text(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return 0


def _run_worker(manifest_path: Path) -> int:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise FakeHostError("unsupported manifest schema")
    events_path = Path(manifest["events_path"])
    events_path.parent.mkdir(parents=True, exist_ok=True)
    _emit(events_path, manifest, "worker_started", task_count=len(manifest["tasks"]))
    completed = 0
    for task in manifest["tasks"]:
        task_id = task["task_id"]
        _emit(
            events_path,
            manifest,
            "task_started",
            task_id=task_id,
            sequence=task["sequence"],
            source_path=task["source_path"],
            output_path=task["output_path"],
        )
        source = Path(task["source_path"])
        mode = _fixture_mode(source)
        status = "Failed"
        output_size = 0
        error_message = "fake conversion failed"
        if mode == "success":
            staging = Path(task["staging_output_path"])
            staging.parent.mkdir(parents=True, exist_ok=True)
            staging.write_bytes(FAKE_ACIS_BYTES)
            status = "Success"
            output_size = staging.stat().st_size
            error_message = ""
        _emit(
            events_path,
            manifest,
            "task_finished",
            task_id=task_id,
            sequence=task["sequence"],
            source_name=source.name,
            source_path=str(source),
            output_name=Path(task["output_path"]).name,
            output_path=task["output_path"],
            staging_output_path=task["staging_output_path"],
            output_format=task["output_format"],
            source_size_bytes=source.stat().st_size,
            output_size_bytes=output_size,
            start_time=_now(),
            duration_seconds=0.01,
            status=status,
            error_message=error_message,
            finish_time=_now(),
        )
        completed += 1
    _emit(events_path, manifest, "worker_finished", completed_task_count=completed)
    return 0


def _fixture_mode(path: Path) -> str:
    content = path.read_text(encoding="utf-8").strip()
    if not content.startswith("MODE:"):
        raise FakeHostError("synthetic fixture must start with MODE:")
    mode = content.split(":", 1)[1].strip().casefold()
    if mode not in {"success", "failed"}:
        raise FakeHostError("unsupported synthetic fixture mode")
    return mode


def _emit(path: Path, manifest: dict, event_name: str, task_id=None, **payload) -> None:
    event = {
        "schema_version": 1,
        "run_id": manifest["run_id"],
        "chunk_id": manifest["chunk_id"],
        "event": event_name,
        "timestamp_utc": _now(),
        "pid": os.getpid(),
    }
    if task_id is not None:
        event["task_id"] = task_id
    event.update(payload)
    with path.open("a", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n")
        output.flush()
        if event_name == "task_finished":
            os.fsync(output.fileno())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main(arguments=None) -> int:
    try:
        parsed = parse_arguments(list(sys.argv[1:] if arguments is None else arguments))
        return run_script(parsed.script, parsed.script_output)
    except (FakeHostError, OSError, UnicodeError, json.JSONDecodeError) as error:
        print("FAKE SPACECLAIM ERROR: {}".format(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
