import json
import os
from pathlib import Path

from .runtime_paths import RuntimePaths


def portable_config_payload(spaceclaim_exe: Path) -> dict[str, object]:
    return {
        "spaceclaim_exe": str(spaceclaim_exe.resolve()),
        "input_dir": "",
        "output_dir": "",
        "recursive": False,
        "output_formats": ["SAB"],
        "overwrite_policy": "Skip",
        "acis_version": "V22",
        "acis_units": "Millimeters",
        "chunk_size": 20,
        "heartbeat_timeout_seconds": 900,
        "retry_count": 0,
        "preserve_relative_directories": True,
        "long_path_warning_threshold": 240,
    }


def write_portable_config(path: Path, spaceclaim_exe: Path) -> None:
    _atomic_json_write(path, portable_config_payload(spaceclaim_exe))


def portable_paths_marker_path(paths: RuntimePaths) -> Path:
    return paths.state_root / "portable_paths.json"

def mark_portable_paths_accepted(path: Path) -> None:
    _atomic_json_write(path, {"schema": 1, "paths_accepted": True})


def has_accepted_portable_paths(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("schema") == 1
        and payload.get("paths_accepted") is True
    )


def _atomic_json_write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".tmp")
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    except Exception:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise
