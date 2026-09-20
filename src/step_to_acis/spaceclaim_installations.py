from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import ctypes
import os
from pathlib import Path
import re
from typing import Literal

from .windows_file_version import FileVersionError, FileVersionInfo, read_file_version
from .spaceclaim_versions import RELEASES, SpaceClaimRelease, release_for_versions


Eligibility = Literal["eligible", "unsupported", "unreadable", "missing"]


@dataclass(frozen=True)
class SpaceClaimCandidate:
    executable: Path
    product_version: str
    file_version: str
    layout_version: str
    sources: tuple[str, ...]
    eligibility: Eligibility
    reason: str

    @property
    def release(self) -> SpaceClaimRelease:
        release = release_for_versions(self.product_version, self.file_version)
        if self.layout_version.casefold() != release.layout:
            raise ValueError("SpaceClaim layout and version metadata do not match")
        return release


def candidate_paths(
    *,
    environ: Mapping[str, str],
    drive_roots: Sequence[Path],
    registry_values: Sequence[str],
    previous: Path | None,
) -> tuple[tuple[Path, tuple[str, ...]], ...]:
    found: dict[str, tuple[Path, set[str]]] = {}

    def add(path: Path, source: str) -> None:
        resolved = path.resolve(strict=False)
        key = os.path.normcase(str(resolved)).casefold()
        if key not in found:
            found[key] = (resolved, set())
        found[key][1].add(source)

    for release in RELEASES:
        awp_root = environ.get("AWP_ROOT" + release.layout[1:])
        if awp_root:
            add(Path(awp_root) / "SCDM" / "SpaceClaim.exe", "environment")

    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        value = environ.get(variable)
        if value:
            _add_versioned_root(Path(value) / "ANSYS Inc", "program_files", add)

    for drive_root in drive_roots:
        _add_versioned_root(drive_root / "ANSYS Inc", "fixed_drive", add)
        _add_versioned_root(
            drive_root / "Program Files" / "ANSYS Inc",
            "fixed_drive",
            add,
        )

    for raw_value in registry_values:
        for path in _registry_candidate_paths(raw_value):
            add(path, "registry")

    if previous is not None and previous.is_file():
        add(previous, "previous")

    return tuple(
        (path, tuple(sorted(sources)))
        for path, sources in sorted(found.values(), key=lambda item: str(item[0]).casefold())
    )


def classify_candidate(
    path: Path,
    *,
    version_reader: Callable[[Path], FileVersionInfo] = read_file_version,
    sources: Sequence[str] = (),
) -> SpaceClaimCandidate:
    executable = path.resolve(strict=False)
    layout_version = _layout_version(executable)
    if not executable.is_file():
        return SpaceClaimCandidate(
            executable, "", "", layout_version, tuple(sources), "missing",
            "SpaceClaim executable does not exist",
        )
    try:
        version = version_reader(executable)
    except (FileVersionError, OSError) as error:
        return SpaceClaimCandidate(
            executable, "", "", layout_version, tuple(sources), "unreadable",
            "cannot read SpaceClaim version metadata: {}".format(error),
        )
    if layout_version.casefold() not in {release.layout for release in RELEASES}:
        return SpaceClaimCandidate(
            executable,
            version.product_version,
            version.file_version,
            layout_version,
            tuple(sources),
            "unsupported",
            "only the v222 / v261 layouts are supported",
        )
    try:
        release = release_for_versions(version.product_version, version.file_version)
        if layout_version.casefold() != release.layout:
            raise ValueError("installation layout does not match version metadata")
    except ValueError as error:
        return SpaceClaimCandidate(
            executable,
            version.product_version,
            version.file_version,
            layout_version,
            tuple(sources),
            "unsupported",
            "SpaceClaim 2022 R2 / 2026 R1 validation failed: {}".format(error),
        )
    return SpaceClaimCandidate(
        executable,
        version.product_version,
        version.file_version,
        layout_version,
        tuple(sources),
        "eligible",
        "{}/{} may be capability-probed".format(release.label, release.layout),
    )


def discover_spaceclaim(
    *,
    environ: Mapping[str, str] | None = None,
    previous: Path | None = None,
    registry_reader: Callable[[], Sequence[str]] | None = None,
    drives_reader: Callable[[], Sequence[Path]] | None = None,
    version_reader: Callable[[Path], FileVersionInfo] = read_file_version,
) -> tuple[SpaceClaimCandidate, ...]:
    environment = os.environ if environ is None else environ
    raw_candidates = candidate_paths(
        environ=environment,
        drive_roots=tuple((drives_reader or _fixed_drive_roots)()),
        registry_values=tuple((registry_reader or _registry_install_values)()),
        previous=previous,
    )
    candidates = tuple(
        classify_candidate(path, version_reader=version_reader, sources=sources)
        for path, sources in raw_candidates
    )
    rank = {"eligible": 0, "unsupported": 1, "unreadable": 2, "missing": 3}
    return tuple(
        sorted(candidates, key=lambda item: (rank[item.eligibility], str(item.executable).casefold()))
    )


def validate_manual_selection(
    path: Path,
    *,
    version_reader: Callable[[Path], FileVersionInfo] = read_file_version,
) -> SpaceClaimCandidate:
    return classify_candidate(path, version_reader=version_reader, sources=("manual",))


def _layout_version(path: Path) -> str:
    if path.name.casefold() != "spaceclaim.exe" or path.parent.name.casefold() != "scdm":
        return ""
    value = path.parent.parent.name
    return value if re.fullmatch(r"v\d+", value, re.IGNORECASE) else ""


def _add_versioned_root(root: Path, source: str, add) -> None:
    try:
        paths = root.glob("v*/SCDM/SpaceClaim.exe")
        for path in paths:
            if path.is_file():
                add(path, source)
    except OSError:
        return


def _registry_candidate_paths(value: str) -> tuple[Path, ...]:
    cleaned = value.strip().strip('"')
    if "," in cleaned:
        cleaned = cleaned.split(",", 1)[0].strip().strip('"')
    if not cleaned:
        return ()
    path = Path(cleaned)
    if path.name.casefold() == "spaceclaim.exe":
        return (path,)
    return (path / "SpaceClaim.exe", path / "SCDM" / "SpaceClaim.exe")


def _fixed_drive_roots() -> tuple[Path, ...]:
    try:
        get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
    except AttributeError:
        return ()
    roots = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        root = Path("{}:\\".format(letter))
        if get_drive_type(str(root)) == 3:
            roots.append(root)
    return tuple(roots)


def _registry_install_values() -> tuple[str, ...]:
    try:
        import winreg
    except ImportError:
        return ()
    values = []
    uninstall = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, uninstall, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with root:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                try:
                    child = winreg.OpenKey(root, name)
                except OSError:
                    continue
                with child:
                    try:
                        display_name = str(winreg.QueryValueEx(child, "DisplayName")[0])
                    except OSError:
                        continue
                    if "spaceclaim" not in display_name.casefold() and "ansys" not in display_name.casefold():
                        continue
                    for field in ("InstallLocation", "DisplayIcon"):
                        try:
                            values.append(str(winreg.QueryValueEx(child, field)[0]))
                        except OSError:
                            pass
    return tuple(values)
