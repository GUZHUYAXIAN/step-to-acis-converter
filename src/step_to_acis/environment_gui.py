from collections.abc import Callable
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .environment_controller import EnvironmentController
from .environment_models import EnvironmentState


_STATUS_ZH = {
    "pass": "通过",
    "warning": "警告",
    "failure": "失败",
    "pending": "等待",
}


def render_environment_details(state: EnvironmentState) -> str:
    lines = []
    for check in state.checks:
        lines.extend(
            (
                "[{}] {}".format(_STATUS_ZH[check.status], check.summary_zh),
                "原因：{}".format(check.reason_zh),
                "修复建议：{}".format(check.remediation_zh),
                "",
            )
        )
    lines.append("自检报告：{}".format(state.report_path or "尚未生成"))
    return "\n".join(lines)


class EnvironmentCheckGui:
    def __init__(
        self,
        root: tk.Tk,
        *,
        controller: EnvironmentController,
        on_approved: Callable[[EnvironmentState], None],
        view_factory=None,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
        file_picker: Callable[..., str] = filedialog.askopenfilename,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.root = root
        self.controller = controller
        self.on_approved = on_approved
        self.thread_factory = thread_factory
        self.file_picker = file_picker
        self.clock = clock
        self._started_at = None
        self._progress_message = ""
        self.event_queue: queue.Queue = queue.Queue()
        self.controller.set_progress_callback(
            lambda message: self.event_queue.put(("progress", message))
        )
        self._worker_active = False
        self._worker_thread = None
        self._destroyed = False
        factory = view_factory or _TkEnvironmentView
        self.view = factory(root)
        self.view.bind_controller(self)
        self.view.render(controller.state)

    def rescan(self) -> None:
        self._start_operation(self.controller.scan, "正在扫描 SpaceClaim 安装位置…")

    def select_candidate(self, executable: Path) -> None:
        self._start_operation(
            lambda: self.controller.select_manual(executable)
        )

    def browse_executable(self) -> None:
        if self._worker_active:
            return
        selected = self.file_picker(
            filetypes=[("SpaceClaim", "SpaceClaim.exe")]
        )
        if selected:
            self._start_operation(
                lambda: self.controller.select_manual(Path(selected))
            )

    def reprobe(self) -> None:
        self._start_operation(self.controller.reprobe, "正在准备重新探测 SpaceClaim…")

    def enter_converter(self) -> None:
        state = self.controller.state
        if self._worker_active or not state.can_enter_converter:
            self.view.show_error("环境自检尚未全部通过，不能进入转换工具。")
            return
        self.on_approved(state)

    def poll_events(self) -> None:
        if self._destroyed:
            return
        while True:
            try:
                kind, value = self.event_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                self._progress_message = value
                continue
            self._worker_active = False
            self.view.set_busy(False)
            if kind == "state":
                self.view.render(value)
            else:
                failed_state = self.controller.fail_closed(value)
                self.view.render(failed_state)
                self.view.show_error(str(value))
            self.view.show_progress("自检结束", self._elapsed())
        if self._worker_active:
            self.view.show_progress(self._progress_message, self._elapsed())
        self.root.after(100, self.poll_events)

    def destroy(self) -> None:
        self._destroyed = True
        self.view.destroy()

    def _elapsed(self) -> float:
        return 0.0 if self._started_at is None else max(0.0, self.clock() - self._started_at)

    def _start_operation(
        self, operation: Callable[[], EnvironmentState],
        message: str = "正在检查所选 SpaceClaim…",
    ) -> None:
        if self._worker_active:
            return
        self._worker_active = True
        self._started_at = self.clock()
        self._progress_message = message
        self.view.set_busy(True)
        self.view.show_progress(message, 0.0)
        self._worker_thread = self.thread_factory(
            target=lambda: self._run_operation(operation),
            daemon=True,
        )
        try:
            self._worker_thread.start()
        except Exception as error:
            self.event_queue.put(("error", error))

    def _run_operation(self, operation: Callable[[], EnvironmentState]) -> None:
        try:
            self.event_queue.put(("state", operation()))
        except Exception as error:
            self.event_queue.put(("error", error))


class _TkEnvironmentView:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.controller = None
        self.state = EnvironmentState()
        self.candidate_var = tk.StringVar(value="等待扫描…")
        self.summary_var = tk.StringVar(value="等待环境自检")
        self.progress_var = tk.StringVar(value="正在准备环境自检…")
        self.frame = ttk.Frame(root, padding=12)
        self.frame.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(6, weight=1)

        ttk.Label(self.frame, text="环境自检", font=("Microsoft YaHei UI", 16, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 10)
        )
        ttk.Label(self.frame, text="SpaceClaim 候选").grid(row=1, column=0, sticky="w")
        self.candidate_box = ttk.Combobox(
            self.frame,
            textvariable=self.candidate_var,
            state="readonly",
            width=72,
        )
        self.candidate_box.grid(row=1, column=1, columnspan=3, sticky="ew", pady=4)
        ttk.Label(self.frame, textvariable=self.summary_var).grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(4, 6)
        )
        self.progress_bar = ttk.Progressbar(self.frame, mode="indeterminate")
        self.progress_bar.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(0, 4))
        ttk.Label(self.frame, textvariable=self.progress_var).grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(0, 6)
        )
        self.checks = ttk.Treeview(
            self.frame,
            columns=("status", "summary"),
            show="headings",
            height=9,
        )
        self.checks.heading("status", text="状态")
        self.checks.heading("summary", text="检查项")
        self.checks.column("status", width=80, stretch=False)
        self.checks.column("summary", width=620)
        self.checks.grid(row=5, column=0, columnspan=4, sticky="nsew")
        self.details = tk.Text(self.frame, height=12, wrap="word", state="disabled")
        self.details.grid(row=6, column=0, columnspan=4, sticky="nsew", pady=(6, 8))

        self.rescan_button = ttk.Button(self.frame, text="重新扫描")
        self.manual_button = ttk.Button(self.frame, text="手动选择 SpaceClaim.exe")
        self.reprobe_button = ttk.Button(self.frame, text="重新探测")
        self.enter_button = ttk.Button(self.frame, text="进入转换工具")
        for column, button in enumerate(
            (self.rescan_button, self.manual_button, self.reprobe_button, self.enter_button)
        ):
            button.grid(row=7, column=column, sticky="ew", padx=(0 if column == 0 else 4, 0))

    def bind_controller(self, controller: EnvironmentCheckGui) -> None:
        self.controller = controller
        self.rescan_button.configure(command=controller.rescan)
        self.manual_button.configure(command=controller.browse_executable)
        self.reprobe_button.configure(command=controller.reprobe)
        self.enter_button.configure(command=controller.enter_converter)
        self.candidate_box.bind(
            "<<ComboboxSelected>>",
            lambda _event: controller.select_candidate(Path(self.candidate_var.get())),
        )

    def render(self, state: EnvironmentState) -> None:
        self.state = state
        placeholder = "未找到可用安装" if state.checks else "等待扫描…"
        candidate_values = [str(candidate.executable) for candidate in state.candidates]
        self.candidate_box.configure(values=candidate_values)
        self.candidate_var.set(
            str(state.selected.executable) if state.selected is not None else placeholder
        )
        for item in self.checks.get_children():
            self.checks.delete(item)
        for check in state.checks:
            self.checks.insert("", "end", values=(_STATUS_ZH[check.status], check.summary_zh))
        self.summary_var.set(
            "环境自检通过，可以进入转换工具。"
            if state.can_enter_converter
            else ("环境自检未通过，请查看原因和修复建议。" if state.checks else "正在准备环境自检…")
        )
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", render_environment_details(state))
        self.details.configure(state="disabled")
        self.enter_button.configure(state="normal" if state.can_enter_converter else "disabled")

    def set_busy(self, busy: bool) -> None:
        self.candidate_box.configure(state="disabled" if busy else "readonly")
        if busy:
            self.summary_var.set("环境自检进行中，请稍候…")
            if self.state.selected is None:
                self.candidate_var.set("正在检测，请稍候…")
            self.progress_bar.start(15)
        else:
            self.progress_bar.stop()
        state = "disabled" if busy else "normal"
        for button in (self.rescan_button, self.manual_button, self.reprobe_button):
            button.configure(state=state)
        self.enter_button.configure(
            state="normal" if not busy and self.state.can_enter_converter else "disabled"
        )

    def show_progress(self, message: str, elapsed: float) -> None:
        self.progress_var.set("{}    已用时 {:.0f} 秒".format(message, elapsed))

    def show_error(self, message: str) -> None:
        messagebox.showerror("环境自检", message, parent=self.root)

    def destroy(self) -> None:
        self.progress_bar.stop()
        self.frame.destroy()
