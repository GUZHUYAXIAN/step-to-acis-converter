from collections import defaultdict
import hashlib
import os
from pathlib import Path
from typing import Iterable

from .models import (
    ConversionResult,
    ConversionTask,
    ConverterConfig,
    OutputFormat,
    OverwritePolicy,
    Status,
)


STEP_EXTENSIONS = frozenset([".stp", ".step"])
ACIS_EXTENSIONS = frozenset([".sab", ".sat"])


class DiscoveryError(RuntimeError):
    pass


class OutputSafetyError(ValueError):
    pass


def scan_step_files(input_root: Path, recursive: bool) -> list[Path]:
    try:
        candidates = input_root.rglob("*") if recursive else input_root.iterdir()
        files = [
            path
            for path in candidates
            if path.is_file() and path.suffix.lower() in STEP_EXTENSIONS
        ]
    except OSError as error:
        raise DiscoveryError("cannot scan input directory: {}".format(error)) from error
    return sorted(
        files,
        key=lambda path: path.relative_to(input_root).as_posix().casefold(),
    )


def build_plan(
    config: ConverterConfig,
    selected_files: Iterable[Path] | None = None,
) -> tuple[list[ConversionTask], list[ConversionResult]]:
    sources = (
        scan_step_files(config.input_dir, config.recursive)
        if selected_files is None
        else validate_selected_files(config.input_dir, selected_files)
    )
    source_paths = set(sources)
    proposals = []
    sequence = 0
    for source in sources:
        relative = source.relative_to(config.input_dir)
        output_parent = _output_parent(config, relative)
        for output_format in config.acis.output_formats:
            sequence += 1
            output_path = output_parent / (source.stem + output_format.extension)
            assert_safe_output(output_path, config.output_dir, source_paths)
            task_id = _task_id(relative, output_format)
            staging = output_path.with_name(
                ".{}.{}.partial{}".format(source.stem, task_id, output_format.extension)
            )
            assert_safe_output(staging, config.output_dir, source_paths)
            proposals.append(
                ConversionTask(
                    sequence=sequence,
                    task_id=task_id,
                    source_path=source,
                    output_path=output_path,
                    staging_output_path=staging,
                    output_format=output_format,
                    source_size_bytes=source.stat().st_size,
                    requires_spaceclaim_path_probe=max(
                        len(str(source)),
                        len(str(output_path)),
                        len(str(staging)),
                    )
                    > config.long_path_warning_threshold,
                )
            )

    collisions = _collision_task_ids(proposals)
    tasks = []
    preflight = []
    for task in proposals:
        if task.task_id in collisions:
            preflight.append(
                _preflight_result(
                    task,
                    Status.FAILED,
                    "output collision: multiple STEP files map to {}".format(
                        task.output_path
                    ),
                )
            )
            continue
        if (
            config.overwrite_policy is OverwritePolicy.SKIP
            and task.output_path.exists()
        ):
            preflight.append(_preflight_result(task, Status.SKIPPED, "output exists"))
            continue
        tasks.append(task)
    return tasks, preflight


def validate_selected_files(input_root: Path, selected_files: Iterable[Path]) -> list[Path]:
    """An explicit selection never falls back to scanning the whole directory."""
    root = input_root.resolve()
    sources = {}
    for selected in selected_files:
        path = Path(selected).resolve()
        if path.suffix.lower() not in STEP_EXTENSIONS:
            raise DiscoveryError("只能点选 STP/STEP 文件：{}".format(path))
        if not path.is_file():
            raise DiscoveryError("所选文件不存在或无法读取，请重新选择：{}".format(path))
        try:
            path.relative_to(root)
        except ValueError as error:
            raise DiscoveryError("所选文件不在当前输入文件夹内，请重新选择：{}".format(path)) from error
        sources[os.path.normcase(str(path))] = path
    if not sources:
        raise DiscoveryError("尚未点选 STP/STEP 文件；请选择文件或切回文件夹扫描。")
    return sorted(sources.values(), key=lambda path: path.relative_to(root).as_posix().casefold())


def assert_safe_output(
    output: Path,
    output_root: Path,
    source_paths: Iterable[Path],
) -> None:
    resolved_output = output.resolve(strict=False)
    resolved_root = output_root.resolve(strict=False)
    if output.suffix.lower() not in ACIS_EXTENSIONS:
        raise OutputSafetyError("output extension must be .sab or .sat")
    try:
        common = os.path.commonpath([str(resolved_output), str(resolved_root)])
    except ValueError as error:
        raise OutputSafetyError("output is on a different volume") from error
    if os.path.normcase(common) != os.path.normcase(str(resolved_root)):
        raise OutputSafetyError("output is outside the configured output directory")
    normalized_sources = {
        os.path.normcase(str(path.resolve(strict=False))) for path in source_paths
    }
    if os.path.normcase(str(resolved_output)) in normalized_sources:
        raise OutputSafetyError("output path equals a source STEP path")


def _output_parent(config: ConverterConfig, relative_source: Path) -> Path:
    if config.preserve_relative_directories:
        return config.output_dir / relative_source.parent
    return config.output_dir


def _task_id(relative_source: Path, output_format: OutputFormat) -> str:
    identity = "{}|{}".format(
        relative_source.as_posix().casefold(),
        output_format.value,
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _collision_task_ids(tasks: Iterable[ConversionTask]) -> set[str]:
    grouped = defaultdict(list)
    for task in tasks:
        key = os.path.normcase(str(task.output_path.resolve(strict=False)))
        grouped[key].append(task)
    return {
        task.task_id
        for grouped_tasks in grouped.values()
        if len(grouped_tasks) > 1
        for task in grouped_tasks
    }


def _preflight_result(
    task: ConversionTask,
    status: Status,
    error_message: str,
) -> ConversionResult:
    output_size = 0
    if task.output_path.is_file():
        output_size = task.output_path.stat().st_size
    return ConversionResult(
        sequence=task.sequence,
        task_id=task.task_id,
        source_name=task.source_path.name,
        source_path=str(task.source_path),
        output_name=task.output_path.name,
        output_path=str(task.output_path),
        output_format=task.output_format.value,
        source_size_bytes=task.source_size_bytes,
        output_size_bytes=output_size,
        start_time="",
        duration_seconds=0.0,
        status=status,
        error_message=error_message,
    )
