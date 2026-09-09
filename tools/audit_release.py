import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile


REQUIRED_TOP_LEVEL = {
    "STEP转ACIS.exe",
    "_internal",
    "README.md",
    "RELEASE_NOTES.md",
    "LICENSE",
    "licenses",
}
ALLOWED_RESOURCES = {"probe_v22.py", "worker_v22.py"}
FORBIDDEN_PARTS = {
    ".git",
    ".worktrees",
    "tests",
    "tools",
    ".validation",
    "conversion_logs",
    "gui_settings.json",
    "selected_spaceclaim.json",
    "selected-spaceclaim.json",
    "capability_profiles",
    "probe-runs",
    "converter_config.json",
    "spaceclaim_cli_profile.json",
}
FORBIDDEN_SUFFIXES = {".stp", ".step", ".sab", ".sat", ".csv", ".log"}


class AuditError(ValueError):
    pass


def audit_release(staging: Path, zip_path: Path | None, repo_root: Path) -> None:
    staging = staging.resolve()
    repo_root = repo_root.resolve()
    if not staging.is_dir():
        raise AuditError("staging directory is missing: {}".format(staging))
    staged = {
        path.relative_to(staging).as_posix(): path.read_bytes()
        for path in staging.rglob("*")
        if path.is_file()
    }
    _audit_entries(staged, repo_root, "staging")
    if zip_path is not None:
        _audit_zip(zip_path.resolve(), repo_root)


def _audit_zip(path: Path, repo_root: Path) -> None:
    if not path.is_file():
        raise AuditError("ZIP is missing: {}".format(path))
    try:
        with zipfile.ZipFile(path, "r") as archive:
            entries = {}
            for info in archive.infolist():
                normalized = PurePosixPath(info.filename.replace("\\", "/"))
                if normalized.is_absolute() or ".." in normalized.parts:
                    raise AuditError("unsafe ZIP entry: {}".format(info.filename))
                if not info.is_dir():
                    entries[normalized.as_posix()] = archive.read(info)
    except (OSError, zipfile.BadZipFile) as error:
        raise AuditError("cannot read ZIP: {}".format(error)) from error
    _audit_entries(entries, repo_root, "ZIP")


def _audit_entries(entries: dict[str, bytes], repo_root: Path, label: str) -> None:
    top_level = {PurePosixPath(name).parts[0] for name in entries}
    if top_level != REQUIRED_TOP_LEVEL:
        raise AuditError(
            "{} top-level entries differ: expected {}, found {}".format(
                label, sorted(REQUIRED_TOP_LEVEL), sorted(top_level)
            )
        )
    resources = {
        PurePosixPath(name).name
        for name in entries
        if PurePosixPath(name).parent.as_posix() == "_internal/resources"
    }
    if resources != ALLOWED_RESOURCES:
        raise AuditError(
            "{} resources differ: expected {}, found {}".format(
                label, sorted(ALLOWED_RESOURCES), sorted(resources)
            )
        )

    needles = _private_needles(repo_root)
    for name, content in entries.items():
        path = PurePosixPath(name)
        lowered_parts = tuple(part.casefold() for part in path.parts)
        lowered = path.as_posix().casefold()
        if any(part in FORBIDDEN_PARTS for part in lowered_parts):
            raise AuditError("{} contains forbidden path: {}".format(label, name))
        if "docs/superpowers" in lowered:
            raise AuditError("{} contains development plans: {}".format(label, name))
        if path.suffix.casefold() in FORBIDDEN_SUFFIXES:
            raise AuditError("{} contains forbidden extension: {}".format(label, name))
        if lowered.startswith("_internal/resources/") and path.name not in ALLOWED_RESOURCES:
            raise AuditError("{} contains unexpected runtime resource: {}".format(label, name))
        for description, needle in needles:
            if needle and needle in content:
                raise AuditError(
                    "{} contains private byte sequence ({}) in {}".format(
                        label, description, name
                    )
                )


def _private_needles(repo_root: Path) -> list[tuple[str, bytes]]:
    values = {str(repo_root), str(repo_root).replace("\\", "/")}
    home = Path.home().resolve()
    values.update({str(home), str(home).replace("\\", "/")})
    for parent in repo_root.parents:
        if parent.parent == parent or len(str(parent)) <= 3:
            continue
        values.update({str(parent), str(parent).replace("\\", "/")})
    for name in ("converter_config.json", "spaceclaim_cli_profile.json"):
        path = repo_root / name
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        values.update(_absolute_strings(payload))
    needles = []
    for value in sorted(values, key=str.casefold):
        if not value:
            continue
        needles.append((value, value.encode("utf-8")))
        needles.append((value + " UTF-16LE", value.encode("utf-16le")))
    return needles


def _absolute_strings(value) -> set[str]:
    found = set()
    if isinstance(value, dict):
        for item in value.values():
            found.update(_absolute_strings(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_absolute_strings(item))
    elif isinstance(value, str) and re.match(r"^[A-Za-z]:[\\/]", value):
        found.update({value, value.replace("\\", "/")})
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Audit portable staging and ZIP privacy")
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--zip", dest="zip_path", type=Path)
    parser.add_argument("--repo-root", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        audit_release(arguments.staging, arguments.zip_path, arguments.repo_root)
    except AuditError as error:
        print("RELEASE AUDIT FAILED: {}".format(error), file=sys.stderr)
        return 1
    print("RELEASE AUDIT PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
