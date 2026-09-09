from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path

from .probe_runner import CliCapabilityProfile
from .spaceclaim_installations import SpaceClaimCandidate


@dataclass(frozen=True)
class ExecutableIdentity:
    absolute_path: str
    sha256: str
    product_version: str
    file_version: str


@dataclass(frozen=True)
class CachedCapability:
    identity: ExecutableIdentity
    profile: CliCapabilityProfile
    probe_completed: bool
    probe_report: str
    verified_at: str


def executable_identity(candidate: SpaceClaimCandidate) -> ExecutableIdentity:
    executable = candidate.executable.resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)
    digest = hashlib.sha256()
    with executable.open("rb") as binary_file:
        for block in iter(lambda: binary_file.read(1024 * 1024), b""):
            digest.update(block)
    return ExecutableIdentity(
        str(executable),
        digest.hexdigest().upper(),
        candidate.product_version,
        candidate.file_version,
    )


def cache_path(root: Path, identity: ExecutableIdentity) -> Path:
    return root / (identity.sha256.upper() + ".json")


def load_cached_capability(
    path: Path,
    current: ExecutableIdentity,
) -> CachedCapability | None:
    if not Path(current.absolute_path).is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("cache_schema") != 2:
            return None
        identity_payload = payload["identity"]
        identity = ExecutableIdentity(
            absolute_path=str(identity_payload["absolute_path"]),
            sha256=str(identity_payload["sha256"]).upper(),
            product_version=str(identity_payload["product_version"]),
            file_version=str(identity_payload["file_version"]),
        )
        if not _identity_matches(identity, current):
            return None
        if payload.get("probe_completed") is not True:
            return None
        capabilities = payload["capabilities"]
        profile = CliCapabilityProfile(
            run_script=capabilities["run_script"] is True,
            script_api_v22=capabilities["script_api_v22"] is True,
            exit_after_script=capabilities["exit_after_script"] is True,
            headless=capabilities["headless"] is True,
            script_args=capabilities["script_args"] is True,
            script_output=capabilities["script_output"] is True,
            script_args_strategy=str(capabilities["script_args_strategy"]),
        )
        if not _profile_authorizes(profile):
            return None
        return CachedCapability(
            identity=identity,
            profile=profile,
            probe_completed=True,
            probe_report=str(payload["probe_report"]),
            verified_at=str(payload["verified_at"]),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
        return None


def save_cached_capability(path: Path, value: CachedCapability) -> None:
    payload = {
        "cache_schema": 2,
        "identity": asdict(value.identity),
        "probe_completed": value.probe_completed,
        "probe_report": value.probe_report,
        "verified_at": value.verified_at,
        "capabilities": asdict(value.profile),
    }
    _atomic_json_write(path, payload)


def load_selected_executable(path: Path) -> Path | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != 1:
            return None
        executable = Path(payload["identity"]["absolute_path"]).resolve()
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
        return None
    return executable if executable.is_file() else None


def save_selected_executable(path: Path, identity: ExecutableIdentity) -> None:
    _atomic_json_write(path, {"schema": 1, "identity": asdict(identity)})


def _identity_matches(cached: ExecutableIdentity, current: ExecutableIdentity) -> bool:
    return (
        os.path.normcase(cached.absolute_path).casefold()
        == os.path.normcase(current.absolute_path).casefold()
        and cached.sha256.upper() == current.sha256.upper()
        and cached.product_version == current.product_version
        and cached.file_version == current.file_version
    )


def _profile_authorizes(profile: CliCapabilityProfile) -> bool:
    return (
        profile.run_script
        and profile.script_api_v22
        and profile.exit_after_script
        and profile.headless
        and profile.script_args_strategy == "specialized_worker_literal"
    )


def _atomic_json_write(path: Path, payload: dict) -> None:
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
