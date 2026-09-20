from collections.abc import Mapping
from dataclasses import dataclass, replace
import os
from pathlib import Path
from typing import Any

from .config import SUPPORTED_ACIS_VERSIONS
from .models import Status


class GuiInputError(ValueError):
    pass


@dataclass(frozen=True)
class GuiFormValues:
    input_dir: str
    output_dir: str
    output_format: str = "SAB"
    recursive: bool = False
    overwrite_policy: str = "Skip"
    acis_version: str = "V22"
    chunk_size: int = 20
    timeout_seconds: float = 900.0
    retry_count: int = 0

    def to_overrides(self) -> dict[str, Any]:
        values = validate_form_values(self)
        return {
            "input_dir": values.input_dir,
            "output_dir": values.output_dir,
            "output_formats": [values.output_format],
            "recursive": values.recursive,
            "overwrite_policy": values.overwrite_policy,
            "acis_version": values.acis_version,
            "chunk_size": values.chunk_size,
            "heartbeat_timeout_seconds": values.timeout_seconds,
            "retry_count": values.retry_count,
        }


@dataclass(frozen=True)
class GuiEvent:
    kind: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class GuiRunState:
    running: bool = False
    total: int = 0
    completed: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    current_file: str = ""
    pid: int | None = None
    chunk_id: str = ""
    message: str = ""
    csv_path: str = ""
    run_log_path: str = ""
    fatal_error: str = ""


def reduce_gui_state(state: GuiRunState, event: GuiEvent) -> GuiRunState:
    payload = event.payload
    if event.kind == "batch_started":
        return GuiRunState(running=True, total=int(payload.get("total", 0)))
    if event.kind == "status":
        updates = {}
        if payload.get("kind") == "task_started":
            updates["current_file"] = Path(str(payload.get("source_path", ""))).name
        if payload.get("kind") == "process_finished":
            updates["pid"] = None
        elif "pid" in payload:
            updates["pid"] = payload.get("pid")
        if "chunk_id" in payload:
            updates["chunk_id"] = str(payload.get("chunk_id", ""))
        return replace(state, **updates) if updates else state
    if event.kind == "result":
        result = payload["result"]
        return replace(
            state,
            completed=state.completed + 1,
            success=state.success + (result.status is Status.SUCCESS),
            failed=state.failed + (result.status is Status.FAILED),
            skipped=state.skipped + (result.status is Status.SKIPPED),
        )
    if event.kind == "batch_completed":
        message = "批次完成，但存在失败" if state.failed else "批次转换完成"
        return replace(
            state,
            running=False,
            pid=None,
            message=message,
            csv_path=str(payload.get("csv_path", "")),
            run_log_path=str(payload.get("run_log_path", "")),
        )
    if event.kind == "batch_failed":
        error_message = str(payload.get("error_message", ""))
        return replace(
            state,
            running=False,
            pid=None,
            message=error_message,
            fatal_error=error_message,
        )
    return state


def validate_form_values(values: GuiFormValues) -> GuiFormValues:
    if not isinstance(values.input_dir, str) or not values.input_dir.strip():
        raise GuiInputError("input_dir must be a non-empty path")
    if not isinstance(values.output_dir, str) or not values.output_dir.strip():
        raise GuiInputError("output_dir must be a non-empty path")
    input_dir = values.input_dir.strip()
    output_dir = values.output_dir.strip()
    if _normalized_path(input_dir) == _normalized_path(output_dir):
        raise GuiInputError("输入与输出文件夹不能相同，请选择另一个输出目录。（input_dir and output_dir must be distinct）")
    if values.output_format not in {"SAB", "SAT"}:
        raise GuiInputError("output_format must be SAB or SAT")
    if type(values.recursive) is not bool:
        raise GuiInputError("recursive must be true or false")
    if values.overwrite_policy not in {"Skip", "Overwrite"}:
        raise GuiInputError("overwrite_policy must be Skip or Overwrite")
    if values.acis_version not in SUPPORTED_ACIS_VERSIONS:
        raise GuiInputError("acis_version is not supported")
    if type(values.chunk_size) is not int or not 1 <= values.chunk_size <= 100:
        raise GuiInputError("chunk_size must be between 1 and 100")
    if (
        isinstance(values.timeout_seconds, bool)
        or not isinstance(values.timeout_seconds, (int, float))
        or values.timeout_seconds <= 0
    ):
        raise GuiInputError("timeout_seconds must be greater than zero")
    if type(values.retry_count) is not int or not 0 <= values.retry_count <= 1:
        raise GuiInputError("retry_count must be between 0 and 1")
    return GuiFormValues(
        input_dir=input_dir,
        output_dir=output_dir,
        output_format=values.output_format,
        recursive=values.recursive,
        overwrite_policy=values.overwrite_policy,
        acis_version=values.acis_version,
        chunk_size=values.chunk_size,
        timeout_seconds=float(values.timeout_seconds),
        retry_count=values.retry_count,
    )


def _normalized_path(value: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(value)))
