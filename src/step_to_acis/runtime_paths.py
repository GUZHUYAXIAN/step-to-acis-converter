from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import sys


_RESOURCE_NAMES = frozenset({"probe_v22.py", "worker_v22.py"})


@dataclass(frozen=True)
class RuntimePaths:
    resource_root: Path
    state_root: Path
    environment_root: Path
    capability_profiles_root: Path
    probe_runs_root: Path
    gui_settings_path: Path


def resource_root(
    *,
    frozen: bool | None = None,
    module_file: Path | None = None,
) -> Path:
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if is_frozen:
        bundle_root = getattr(sys, "_MEIPASS", None)
        if not bundle_root:
            raise RuntimeError("frozen resource root is unavailable")
        return Path(bundle_root) / "resources"
    source_file = Path(__file__) if module_file is None else module_file
    return source_file.resolve().parents[2] / "spaceclaim"


def resource_path(name: str, *, root: Path | None = None) -> Path:
    if name not in _RESOURCE_NAMES:
        raise ValueError("resource name is not allowed: {!r}".format(name))
    return (resource_root() if root is None else root) / name


def default_runtime_paths(
    environ: Mapping[str, str] | None = None,
) -> RuntimePaths:
    environment = os.environ if environ is None else environ
    local_app_data = environment.get("LOCALAPPDATA")
    local_root = (
        Path(local_app_data)
        if local_app_data
        else Path.home() / "AppData" / "Local"
    )
    state_root = local_root / "SpaceClaimStepToAcis"
    environment_root = state_root / "environment"
    return RuntimePaths(
        resource_root=resource_root(),
        state_root=state_root,
        environment_root=environment_root,
        capability_profiles_root=environment_root / "capability_profiles",
        probe_runs_root=environment_root / "probe-runs",
        gui_settings_path=state_root / "gui_settings.json",
    )
