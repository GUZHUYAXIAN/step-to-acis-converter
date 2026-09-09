import csv
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Iterable, Sequence

from .models import ConversionResult, Status


CSV_COLUMNS = (
    "Sequence",
    "SourceName",
    "SourcePath",
    "OutputName",
    "OutputPath",
    "OutputFormat",
    "SourceSizeBytes",
    "OutputSizeBytes",
    "StartTime",
    "DurationSeconds",
    "Status",
    "ErrorMessage",
)


@dataclass(frozen=True)
class RunSummary:
    total: int
    success: int
    failed: int
    skipped: int
    elapsed_seconds: float


def write_conversion_csv(
    path: Path,
    results: Sequence[ConversionResult],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".tmp")
    with temporary_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS, extrasaction="raise")
        writer.writeheader()
        for result in sorted(results, key=lambda item: item.sequence):
            writer.writerow(_csv_row(result))
        csv_file.flush()
        os.fsync(csv_file.fileno())
    os.replace(temporary_path, path)


def append_run_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as log_file:
        log_file.write(message.rstrip("\r\n") + "\n")
        log_file.flush()


def summarize(
    results: Iterable[ConversionResult],
    elapsed_seconds: float,
) -> RunSummary:
    materialized = list(results)
    success = sum(result.status is Status.SUCCESS for result in materialized)
    failed = sum(result.status is Status.FAILED for result in materialized)
    skipped = sum(result.status is Status.SKIPPED for result in materialized)
    total = len(materialized)
    if total != success + failed + skipped:
        raise ValueError("result contains an unsupported status")
    return RunSummary(total, success, failed, skipped, elapsed_seconds)


def format_size(byte_count: int) -> str:
    if byte_count < 0:
        raise ValueError("byte_count cannot be negative")
    if byte_count < 1024:
        return "{} B".format(byte_count)
    units = ("KB", "MB", "GB", "TB")
    value = float(byte_count)
    for unit in units:
        value /= 1024.0
        if value < 1024.0 or unit == units[-1]:
            return "{:.2f} {}".format(value, unit)
    raise AssertionError("unreachable")


def _csv_row(result: ConversionResult) -> dict[str, object]:
    return {
        "Sequence": result.sequence,
        "SourceName": result.source_name,
        "SourcePath": result.source_path,
        "OutputName": result.output_name,
        "OutputPath": result.output_path,
        "OutputFormat": result.output_format,
        "SourceSizeBytes": result.source_size_bytes,
        "OutputSizeBytes": result.output_size_bytes,
        "StartTime": result.start_time,
        "DurationSeconds": "{:.6f}".format(result.duration_seconds),
        "Status": result.status.value,
        "ErrorMessage": result.error_message,
    }
