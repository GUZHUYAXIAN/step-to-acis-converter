import json
import os
from pathlib import Path
from typing import Any, Mapping

from .models import AcisSettings, ConverterConfig, OutputFormat, OverwritePolicy


SUPPORTED_ACIS_VERSIONS = frozenset(
    ["V6", "V7"] + ["V{}".format(number) for number in range(15, 32)]
)
SUPPORTED_ACIS_UNITS = frozenset(
    ["Meters", "Centimeters", "Millimeters", "Feet", "Inches"]
)
ALLOWED_KEYS = frozenset(
    [
        "spaceclaim_exe",
        "input_dir",
        "output_dir",
        "recursive",
        "output_formats",
        "overwrite_policy",
        "acis_version",
        "acis_units",
        "chunk_size",
        "heartbeat_timeout_seconds",
        "retry_count",
        "preserve_relative_directories",
        "long_path_warning_threshold",
    ]
)


class ConfigError(ValueError):
    pass


def load_config(
    path: Path,
    overrides: Mapping[str, Any] | None = None,
) -> ConverterConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfigError("cannot read configuration: {}".format(error)) from error
    if not isinstance(raw, dict):
        raise ConfigError("configuration root must be a JSON object")
    values = {key: value for key, value in raw.items() if not key.startswith("_comment_")}
    unknown = sorted(set(values) - ALLOWED_KEYS)
    if unknown:
        raise ConfigError("unknown configuration key: {}".format(unknown[0]))
    if overrides:
        override_unknown = sorted(set(overrides) - ALLOWED_KEYS)
        if override_unknown:
            raise ConfigError("unknown configuration key: {}".format(override_unknown[0]))
        values.update({key: value for key, value in overrides.items() if value is not None})
    return _parse_config(values)


def _parse_config(values: Mapping[str, Any]) -> ConverterConfig:
    executable = _required_path(values, "spaceclaim_exe").resolve()
    input_dir = _required_path(values, "input_dir").resolve()
    output_dir = _required_path(values, "output_dir").resolve()
    if not executable.is_file():
        raise ConfigError("spaceclaim_exe is not a file: {}".format(executable))
    if not input_dir.is_dir():
        raise ConfigError("input_dir is not a directory: {}".format(input_dir))
    if _same_path(input_dir, output_dir):
        raise ConfigError("input_dir and output_dir must be distinct")

    recursive = _boolean(values, "recursive", False)
    preserve_relative = _boolean(values, "preserve_relative_directories", True)
    formats = _output_formats(values.get("output_formats", ["SAB"]))
    policy = _enum_value(
        OverwritePolicy,
        values.get("overwrite_policy", "Skip"),
        "overwrite_policy",
    )
    version = values.get("acis_version", "V22")
    if version != "current_spaceclaim_default" and version not in SUPPORTED_ACIS_VERSIONS:
        raise ConfigError("acis_version is not supported by V22: {!r}".format(version))
    units = values.get("acis_units", "Millimeters")
    if units not in SUPPORTED_ACIS_UNITS:
        raise ConfigError("acis_units is invalid: {!r}".format(units))
    chunk_size = _bounded_integer(values, "chunk_size", 20, 1, 100)
    timeout = _positive_number(values, "heartbeat_timeout_seconds", 900.0)
    retry_count = _bounded_integer(values, "retry_count", 0, 0, 1)
    path_threshold = _bounded_integer(
        values,
        "long_path_warning_threshold",
        240,
        1,
        32767,
    )
    return ConverterConfig(
        spaceclaim_exe=executable,
        input_dir=input_dir,
        output_dir=output_dir,
        recursive=recursive,
        acis=AcisSettings(formats, version, units),
        overwrite_policy=policy,
        chunk_size=chunk_size,
        heartbeat_timeout_seconds=timeout,
        retry_count=retry_count,
        preserve_relative_directories=preserve_relative,
        long_path_warning_threshold=path_threshold,
    )


def _required_path(values: Mapping[str, Any], field: str) -> Path:
    value = values.get(field)
    if not isinstance(value, str) or not value:
        raise ConfigError("{} must be a non-empty path string".format(field))
    return Path(value)


def _same_path(first: Path, second: Path) -> bool:
    return os.path.normcase(str(first)) == os.path.normcase(str(second))


def _boolean(values: Mapping[str, Any], field: str, default: bool) -> bool:
    value = values.get(field, default)
    if not isinstance(value, bool):
        raise ConfigError("{} must be true or false".format(field))
    return value


def _output_formats(value: Any) -> tuple[OutputFormat, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigError("output_formats must be a non-empty list")
    try:
        formats = tuple(OutputFormat(item) for item in value)
    except (TypeError, ValueError) as error:
        raise ConfigError("output_formats contains an invalid value") from error
    if len(set(formats)) != len(formats):
        raise ConfigError("output_formats contains a duplicate value")
    return formats


def _enum_value(enum_type, value: Any, field: str):
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        raise ConfigError("{} is invalid: {!r}".format(field, value)) from error


def _bounded_integer(
    values: Mapping[str, Any],
    field: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = values.get(field, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError("{} must be an integer".format(field))
    if value < minimum or value > maximum:
        raise ConfigError(
            "{} must be between {} and {}".format(field, minimum, maximum)
        )
    return value


def _positive_number(values: Mapping[str, Any], field: str, default: float) -> float:
    value = values.get(field, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError("{} must be greater than zero".format(field))
    return float(value)
