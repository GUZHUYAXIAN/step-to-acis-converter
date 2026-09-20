from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Protocol

from .capability_cache import ExecutableIdentity, load_cached_capability
from .config import ConfigError, load_config
from .discovery import DiscoveryError, build_plan
from .models import ConversionResult
from .probe_runner import CliCapabilityProfile
from .reporting import RunSummary, append_run_log, summarize, write_conversion_csv
from .runtime_paths import resource_path
from .spaceclaim_command import SpaceClaimCommand, build_production_command
from .supervisor import BatchSupervisor
from .windows_file_version import FileVersionError, read_file_version
from .spaceclaim_versions import release_for_api, validate_acis_version


class CapabilityProfileError(ValueError):
    pass


@dataclass(frozen=True)
class BatchRequest:
    config_path: Path
    overrides: Mapping[str, Any]
    capability_profile_path: Path
    worker_template_path: Path | None = None
    selected_files: tuple[Path, ...] | None = None


@dataclass(frozen=True)
class BatchOutcome:
    exit_code: int
    summary: RunSummary | None
    results: tuple[ConversionResult, ...]
    run_directory: Path | None
    csv_path: Path | None
    run_log_path: Path | None
    error_kind: str
    error_message: str


class BatchReporter(Protocol):
    def on_batch_started(self, total: int, run_directory: Path) -> None: ...

    def on_status(self, update: dict[str, Any]) -> None: ...

    def on_result(self, result: ConversionResult) -> None: ...


class NullBatchReporter:
    def on_batch_started(self, total: int, run_directory: Path) -> None:
        pass

    def on_status(self, update: dict[str, Any]) -> None:
        pass

    def on_result(self, result: ConversionResult) -> None:
        pass


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run_batch(
    request: BatchRequest,
    reporter: BatchReporter,
    *,
    capability_profile_loader: Callable | None = None,
    supervisor_factory: Callable | None = None,
) -> BatchOutcome:
    try:
        config = load_config(request.config_path, request.overrides)
        tasks, preflight = build_plan(config, request.selected_files)
    except (ConfigError, DiscoveryError, OSError) as error:
        return _error_outcome(2, "preflight", error)

    started = time.perf_counter()
    try:
        run_directory = _create_run_directory(config.output_dir / "conversion_logs")
        run_log = run_directory / "conversion_run.txt"
        csv_path = run_directory / "conversion_log.csv"
        append_run_log(run_log, "SpaceClaim executable: {}".format(config.spaceclaim_exe))
        append_run_log(run_log, "Input mode: {}".format(
            "folder scan" if request.selected_files is None else "selected files only"
        ))
        append_run_log(
            run_log,
            "Configuration: format={} policy={} version={} units={} recursive={} chunk_size={}".format(
                ",".join(item.value for item in config.acis.output_formats),
                config.overwrite_policy.value,
                config.resolved_acis_version,
                config.acis.units,
                config.recursive,
                config.chunk_size,
            ),
        )
    except OSError as error:
        return _error_outcome(4, "log_initialization", error)

    reporter.on_batch_started(len(tasks) + len(preflight), run_directory)
    reported_results: list[ConversionResult] = []

    def report_result(result: ConversionResult) -> None:
        reported_results.append(result)
        reporter.on_result(result)

    try:
        if tasks:
            loader = capability_profile_loader or load_verified_capability_profile
            profile = loader(request.capability_profile_path, config)
            release = release_for_api(profile.api_version)
            validate_acis_version(profile.api_version, config.resolved_acis_version)
            append_run_log(run_log, release.output_note)

            def command_factory(worker: Path, script_output: Path) -> list[str]:
                command = SpaceClaimCommand(
                    executable=config.spaceclaim_exe,
                    script=worker,
                    script_output=script_output if profile.script_output else None,
                    api_version=profile.api_version,
                )
                built = build_production_command(command, profile)
                append_run_log(
                    run_log,
                    "Command: {}".format(json.dumps(built, ensure_ascii=False)),
                )
                return built

            def status_handler(update: dict[str, Any]) -> None:
                reporter.on_status(update)
                if update.get("kind") == "process_started":
                    append_run_log(
                        run_log,
                        "Process started: pid={} chunk={}".format(
                            update.get("pid"),
                            update.get("chunk_id"),
                        ),
                    )
                elif update.get("kind") == "process_finished":
                    append_run_log(
                        run_log,
                        "Process finished: pid={} chunk={} exit_code={} timed_out={}".format(
                            update.get("pid"),
                            update.get("chunk_id"),
                            update.get("returncode"),
                            update.get("timed_out"),
                        ),
                    )
                elif update.get("kind") == "worker_fatal":
                    append_run_log(
                        run_log,
                        "Worker fatal: chunk={} task_id={} error={}".format(
                            update.get("chunk_id"),
                            update.get("task_id", ""),
                            update.get("error_message", ""),
                        ),
                    )

            factory = supervisor_factory or BatchSupervisor
            supervisor = factory(
                config=config,
                run_directory=run_directory / "worker_runs",
                worker_template=(
                    request.worker_template_path or resource_path(release.worker_resource)
                ),
                command_factory=command_factory,
                status_callback=status_handler,
            )
            results = supervisor.run(tasks, preflight, report_result)
        else:
            results = list(preflight)
            for result in preflight:
                report_result(result)

        ordered_results = tuple(sorted(results, key=lambda item: item.sequence))
        elapsed = time.perf_counter() - started
        summary = summarize(ordered_results, elapsed)
        write_conversion_csv(csv_path, ordered_results)
        append_run_log(
            run_log,
            "Summary: total={} success={} failed={} skipped={} elapsed_seconds={:.3f}".format(
                summary.total,
                summary.success,
                summary.failed,
                summary.skipped,
                summary.elapsed_seconds,
            ),
        )
    except CapabilityProfileError as error:
        return BatchOutcome(
            3,
            None,
            tuple(sorted(reported_results, key=lambda item: item.sequence)),
            run_directory,
            csv_path,
            run_log,
            "capability_profile",
            str(error),
        )
    except Exception as error:
        try:
            append_run_log(run_log, "Fatal: {}".format(error))
        except OSError:
            pass
        return BatchOutcome(
            4,
            None,
            tuple(sorted(reported_results, key=lambda item: item.sequence)),
            run_directory,
            csv_path,
            run_log,
            "fatal",
            str(error),
        )

    return BatchOutcome(
        0,
        summary,
        ordered_results,
        run_directory,
        csv_path,
        run_log,
        "",
        "",
    )


def load_verified_capability_profile(
    path: Path,
    config,
) -> CliCapabilityProfile:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CapabilityProfileError("cannot read profile: {}".format(error)) from error
    if payload.get("cache_schema") in (2, 3):
        try:
            version = read_file_version(config.spaceclaim_exe)
            current = ExecutableIdentity(
                absolute_path=str(config.spaceclaim_exe.resolve()),
                sha256=_sha256_file(config.spaceclaim_exe),
                product_version=version.product_version,
                file_version=version.file_version,
            )
        except (OSError, FileVersionError) as error:
            raise CapabilityProfileError(
                "cannot verify SpaceClaim executable identity: {}".format(error)
            ) from error
        cached = load_cached_capability(path, current)
        if cached is None:
            raise CapabilityProfileError("portable capability cache is invalid")
        return cached.profile
    if payload.get("profile_schema") != 1:
        raise CapabilityProfileError("profile schema is not supported")
    profiled_executable = Path(payload.get("spaceclaim_executable", "")).resolve()
    if os.path.normcase(str(profiled_executable)) != os.path.normcase(
        str(config.spaceclaim_exe.resolve())
    ):
        raise CapabilityProfileError("profile was verified for a different executable")
    if _sha256_file(config.spaceclaim_exe) != payload.get("spaceclaim_executable_sha256"):
        raise CapabilityProfileError("SpaceClaim executable hash changed after probing")
    try:
        profile = CliCapabilityProfile(**payload["capabilities"])
        if profile.api_version != "V22":
            raise CapabilityProfileError("2026 R1 requires a fresh version-bound capability cache")
        return profile
    except (KeyError, TypeError) as error:
        raise CapabilityProfileError("profile capabilities are invalid") from error


def _error_outcome(exit_code: int, error_kind: str, error: Exception) -> BatchOutcome:
    return BatchOutcome(exit_code, None, (), None, None, None, error_kind, str(error))


def _create_run_directory(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_directory = root / run_id
    run_directory.mkdir(exist_ok=False)
    return run_directory


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as binary_file:
        for block in iter(lambda: binary_file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()
