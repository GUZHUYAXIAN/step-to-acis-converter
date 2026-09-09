import argparse
from pathlib import Path
import sys
from collections.abc import Callable, Sequence
from typing import TextIO

from .batch_service import (
    BatchOutcome,
    BatchRequest,
    CapabilityProfileError,
    load_verified_capability_profile,
    repository_root,
    run_batch,
)
from .models import ConversionResult, Status
from .reporting import format_size


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="STEP → ACIS batch converter powered by SpaceClaim 2022 R2"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=repository_root() / "converter_config.json",
        help="UTF-8 JSON configuration file",
    )
    parser.add_argument("--input-dir", type=str)
    parser.add_argument("--output-dir", type=str)
    recursion = parser.add_mutually_exclusive_group()
    recursion.add_argument("--recursive", action="store_true", dest="recursive")
    recursion.add_argument("--no-recursive", action="store_false", dest="recursive")
    parser.set_defaults(recursive=None)
    parser.add_argument(
        "--format",
        choices=["SAB", "SAT"],
        default=None,
        help="output format override (default from config: SAB)",
    )
    parser.add_argument(
        "--overwrite-policy",
        choices=["Skip", "Overwrite"],
        default=None,
        help="existing-output policy override (default from config: Skip)",
    )
    parser.add_argument("--acis-version")
    parser.add_argument("--acis-units")
    parser.add_argument("--chunk-size", type=int)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--retry-count", type=int)
    parser.add_argument(
        "--capability-profile",
        type=Path,
        default=repository_root() / "spaceclaim_cli_profile.json",
    )
    return parser


def render_progress_bar(completed: int, total: int, width: int = 24):
    percentage = 100.0 if total == 0 else completed * 100.0 / total
    filled = width if total == 0 else int(round(width * completed / total))
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled), percentage


class ConsoleReporter:
    def __init__(self, stream: TextIO, total: int = 0):
        self.stream = stream
        self.total = total
        self.completed = 0
        self.success = 0
        self.failed = 0
        self.skipped = 0

    def on_batch_started(self, total: int, run_directory: Path) -> None:
        self.total = total

    def on_status(self, update: dict) -> None:
        if update.get("kind") != "task_started":
            return
        sequence = update.get("sequence", "?")
        source = Path(update.get("source_path", "")).name
        self.stream.write(
            "当前：{} / {}  {}  [PID {} | {}]\n".format(
                sequence,
                self.total,
                source,
                update.get("pid", "?"),
                update.get("chunk_id", "?"),
            )
        )
        self.stream.flush()

    def on_result(self, result: ConversionResult) -> None:
        self.completed += 1
        self.success += result.status is Status.SUCCESS
        self.failed += result.status is Status.FAILED
        self.skipped += result.status is Status.SKIPPED
        bar, percentage = render_progress_bar(self.completed, self.total)
        self.stream.write(
            "{}  {:6.2f}%  成功:{}  失败:{}  跳过:{}  {} -> {}  {:.3f}s\n".format(
                bar,
                percentage,
                self.success,
                self.failed,
                self.skipped,
                format_size(result.source_size_bytes),
                format_size(result.output_size_bytes),
                result.duration_seconds,
            )
        )
        self.stream.flush()


def render_batch_outcome(
    outcome: BatchOutcome,
    output_stream: TextIO,
    error_stream: TextIO,
) -> int:
    if outcome.exit_code != 0:
        labels = {
            "preflight": "预检失败",
            "capability_profile": "SpaceClaim 能力档案无效",
            "log_initialization": "日志初始化失败",
            "fatal": "批处理致命错误",
        }
        label = labels.get(outcome.error_kind, "批处理致命错误")
        error_stream.write("{}：{}\n".format(label, outcome.error_message))
        if outcome.run_log_path is not None:
            error_stream.write("运行日志：{}\n".format(outcome.run_log_path))
        error_stream.flush()
        return outcome.exit_code

    summary = outcome.summary
    assert summary is not None
    output_stream.write("\n转换任务完成\n")
    output_stream.write("总文件数：{}\n".format(summary.total))
    output_stream.write("成功：{}\n".format(summary.success))
    output_stream.write("失败：{}\n".format(summary.failed))
    output_stream.write("跳过：{}\n".format(summary.skipped))
    output_stream.write("总耗时：{:.2f} min\n".format(summary.elapsed_seconds / 60.0))
    output_stream.write("转换日志：{}\n".format(outcome.csv_path))
    output_stream.write("运行日志：{}\n".format(outcome.run_log_path))
    if summary.failed:
        output_stream.write(
            "存在 {} 个转换失败文件，请查看 {}\n".format(
                summary.failed,
                outcome.csv_path,
            )
        )
    output_stream.flush()
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    output_stream: TextIO | None = None,
    error_stream: TextIO | None = None,
    capability_profile_loader: Callable | None = None,
    supervisor_factory: Callable | None = None,
) -> int:
    output_stream = output_stream or sys.stdout
    error_stream = error_stream or sys.stderr
    arguments = build_parser().parse_args(argv)
    overrides = {
        "input_dir": arguments.input_dir,
        "output_dir": arguments.output_dir,
        "recursive": arguments.recursive,
        "output_formats": [arguments.format] if arguments.format else None,
        "overwrite_policy": arguments.overwrite_policy,
        "acis_version": arguments.acis_version,
        "acis_units": arguments.acis_units,
        "chunk_size": arguments.chunk_size,
        "heartbeat_timeout_seconds": arguments.timeout,
        "retry_count": arguments.retry_count,
    }
    reporter = ConsoleReporter(output_stream)
    outcome = run_batch(
        BatchRequest(
            config_path=arguments.config,
            overrides=overrides,
            capability_profile_path=arguments.capability_profile,
        ),
        reporter,
        capability_profile_loader=capability_profile_loader,
        supervisor_factory=supervisor_factory,
    )
    return render_batch_outcome(outcome, output_stream, error_stream)
