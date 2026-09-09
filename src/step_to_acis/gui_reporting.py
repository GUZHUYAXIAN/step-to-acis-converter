from pathlib import Path
import queue
from typing import Any

from .batch_service import BatchReporter
from .gui_models import GuiEvent
from .models import ConversionResult


class QueueReporter:
    def __init__(self, event_queue: queue.Queue[GuiEvent]):
        self.event_queue = event_queue

    def on_batch_started(self, total: int, run_directory: Path) -> None:
        self.event_queue.put(
            GuiEvent(
                "batch_started",
                {"total": total, "run_directory": run_directory},
            )
        )

    def on_status(self, update: dict[str, Any]) -> None:
        self.event_queue.put(GuiEvent("status", dict(update)))

    def on_result(self, result: ConversionResult) -> None:
        self.event_queue.put(GuiEvent("result", {"result": result}))


class CompositeReporter:
    def __init__(self, *reporters: BatchReporter):
        self.reporters = reporters

    def on_batch_started(self, total: int, run_directory: Path) -> None:
        for reporter in self.reporters:
            reporter.on_batch_started(total, run_directory)

    def on_status(self, update: dict[str, Any]) -> None:
        for reporter in self.reporters:
            reporter.on_status(update)

    def on_result(self, result: ConversionResult) -> None:
        for reporter in self.reporters:
            reporter.on_result(result)
