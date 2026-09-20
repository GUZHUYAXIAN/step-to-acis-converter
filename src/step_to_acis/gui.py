from dataclasses import replace
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from collections.abc import Callable

from .batch_service import BatchOutcome, BatchRequest, run_batch
from .cli import ConsoleReporter, render_batch_outcome
from .config import load_config
from .discovery import DiscoveryError, validate_selected_files
from .gui_models import (
    GuiEvent,
    GuiFormValues,
    GuiRunState,
    reduce_gui_state,
    validate_form_values,
)
from .gui_reporting import CompositeReporter, QueueReporter
from .gui_settings import default_settings_path, load_gui_settings, save_gui_settings
from .spaceclaim_versions import release_for_api, validate_acis_version


class ConverterGui:
    def __init__(
        self,
        root: tk.Tk,
        *,
        config_path: Path,
        capability_profile_path: Path,
        settings_path: Path,
        worker_template_path: Path | None = None,
        batch_runner: Callable[..., BatchOutcome] = run_batch,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
        view_factory=None,
        defaults: GuiFormValues | None = None,
        restore_saved_paths: bool = True,
        on_settings_saved: Callable[[], None] | None = None,
        api_version: str = "V22",
    ):
        self.root = root
        self.config_path = config_path
        self.capability_profile_path = capability_profile_path
        self.settings_path = settings_path
        self.worker_template_path = worker_template_path
        self.batch_runner = batch_runner
        self.thread_factory = thread_factory
        self.on_settings_saved = on_settings_saved
        self.release = release_for_api(api_version)
        self.event_queue = queue.Queue()
        self.state = GuiRunState()
        self._worker_active = False
        self._worker_thread = None
        self._run_selected_files = None

        if defaults is None:
            config = load_config(config_path)
            defaults = GuiFormValues(
                input_dir=str(config.input_dir),
                output_dir=str(config.output_dir),
                output_format=config.acis.output_formats[0].value,
                recursive=config.recursive,
                overwrite_policy=config.overwrite_policy.value,
                acis_version=config.resolved_acis_version,
                chunk_size=config.chunk_size,
                timeout_seconds=config.heartbeat_timeout_seconds,
                retry_count=config.retry_count,
            )
        values = load_gui_settings(
            settings_path,
            defaults,
            restore_paths=restore_saved_paths,
        )
        version_changed = values.acis_version not in self.release.acis_versions
        if version_changed:
            values = replace(values, acis_version=self.release.default_acis_version)
        self._run_values = values
        factory = view_factory or _TkView
        self.view = factory(root, values)
        if hasattr(self.view, "configure_release"):
            self.view.configure_release(self.release, version_changed)
        if hasattr(self.view, "bind_controller"):
            self.view.bind_controller(self)
        self.root.protocol("WM_DELETE_WINDOW", self.request_close)

    def toggle_advanced(self) -> None:
        self.view.toggle_advanced()

    def update_overwrite_warning(self) -> None:
        self.view.update_overwrite_warning()

    def start_conversion(self) -> None:
        if self._worker_active:
            return
        try:
            values = validate_form_values(self.view.get_form_values())
            validate_acis_version(self.release.api_version, values.acis_version)
            config = load_config(self.config_path, values.to_overrides())
            selected = getattr(self.view, "get_selected_files", lambda: None)()
            selected = None if selected is None else tuple(validate_selected_files(config.input_dir, selected))
            save_gui_settings(self.settings_path, values)
            if self.on_settings_saved is not None:
                self.on_settings_saved()
        except (OSError, ValueError, DiscoveryError) as error:
            self.view.show_error(str(error))
            return
        self._run_values = values
        self._run_selected_files = selected
        self._worker_active = True
        self.state = replace(self.state, running=True)
        self.view.set_controls_enabled(False)
        self._worker_thread = self.thread_factory(target=self._run_worker, daemon=True)
        self._worker_thread.start()

    def _run_worker(self) -> None:
        try:
            values = self._run_values
            reporter = CompositeReporter(
                ConsoleReporter(sys.stdout),
                QueueReporter(self.event_queue),
            )
            outcome = self.batch_runner(
                BatchRequest(
                    config_path=self.config_path,
                    overrides=values.to_overrides(),
                    capability_profile_path=self.capability_profile_path,
                    worker_template_path=self.worker_template_path,
                    selected_files=self._run_selected_files,
                ),
                reporter,
            )
            render_batch_outcome(outcome, sys.stdout, sys.stderr)
            if outcome.exit_code == 0:
                self.event_queue.put(
                    GuiEvent(
                        "batch_completed",
                        {
                            "summary": outcome.summary,
                            "csv_path": outcome.csv_path,
                            "run_log_path": outcome.run_log_path,
                        },
                    )
                )
            else:
                self.event_queue.put(
                    GuiEvent(
                        "batch_failed",
                        {"error_message": outcome.error_message},
                    )
                )
        except Exception as error:
            sys.stderr.write("批处理致命错误：{}\n".format(error))
            sys.stderr.flush()
            self.event_queue.put(
                GuiEvent("batch_failed", {"error_message": str(error)})
            )

    def poll_events(self) -> None:
        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break
            self.state = reduce_gui_state(self.state, event)
            self.view.update_state(self.state)
            self.view.append_event(event)
            if event.kind in {"batch_completed", "batch_failed"}:
                self._worker_active = False
                self.view.set_controls_enabled(True)
        self.root.after(100, self.poll_events)

    def request_close(self) -> None:
        if self._worker_active:
            self.view.show_error("转换正在进行，请等待批次完成后再关闭。")
            return
        self.root.destroy()


class _TkView:
    def __init__(self, root: tk.Tk, values: GuiFormValues):
        self.root = root
        self.advanced_visible = False
        self._controller = None
        self._selected_files = None
        self._controls_enabled = True
        self.selection_var = tk.StringVar(value="文件夹模式：扫描 STP/STEP")
        self.input_var = tk.StringVar(value=values.input_dir)
        self.output_var = tk.StringVar(value=values.output_dir)
        self.format_var = tk.StringVar(value=values.output_format)
        self.recursive_var = tk.BooleanVar(value=values.recursive)
        self.policy_var = tk.StringVar(value=values.overwrite_policy)
        self.version_var = tk.StringVar(value=values.acis_version)
        self.chunk_var = tk.StringVar(value=str(values.chunk_size))
        self.timeout_var = tk.StringVar(value=str(values.timeout_seconds))
        self.retry_var = tk.StringVar(value=str(values.retry_count))
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_text_var = tk.StringVar(value="0 / 0  (0.00%)")
        self.counts_var = tk.StringVar(value="成功 0    失败 0    跳过 0")
        self.current_file_var = tk.StringVar(value="当前文件：—")
        self.process_var = tk.StringVar(value="PID / Chunk：—")
        self.message_var = tk.StringVar(value="就绪")
        self.paths_var = tk.StringVar(value="CSV / TXT：—")
        self.release_var = tk.StringVar(value="")
        self._editable = []
        self._build()
        self.input_var.trace_add("write", lambda *_: self.clear_file_selection())

    def bind_controller(self, controller: ConverterGui) -> None:
        self._controller = controller
        self.start_button.configure(command=controller.start_conversion)
        self.advanced_button.configure(command=controller.toggle_advanced)
        for radio in self.policy_radios:
            radio.configure(command=controller.update_overwrite_warning)

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        self._folder_row(frame, 0, "输入文件夹", self.input_var)
        self._folder_row(frame, 1, "输出文件夹", self.output_var)

        selection_bar = ttk.Frame(frame)
        selection_bar.grid(row=2, column=0, columnspan=3, sticky="ew", pady=4)
        choose_files = ttk.Button(selection_bar, text="点选 STEP 文件…", command=self.choose_step_files)
        choose_files.pack(side="left")
        clear_files = ttk.Button(selection_bar, text="切回文件夹扫描", command=self.clear_file_selection)
        clear_files.pack(side="left", padx=6)
        ttk.Label(selection_bar, textvariable=self.selection_var).pack(side="left")
        self._editable.extend([choose_files, clear_files])
        self.selected_text = scrolledtext.ScrolledText(frame, height=3, wrap="word", state="disabled")
        self.selected_text.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        self.selected_text.grid_remove()

        ttk.Label(frame, text="输出格式").grid(row=4, column=0, sticky="w", pady=4)
        format_box = ttk.Frame(frame)
        format_box.grid(row=4, column=1, sticky="w")
        for value in ("SAB", "SAT"):
            widget = ttk.Radiobutton(format_box, text=value, variable=self.format_var, value=value)
            widget.pack(side="left", padx=(0, 12))
            self._editable.append(widget)
        recursive = ttk.Checkbutton(frame, text="包含子文件夹", variable=self.recursive_var)
        self.recursive_check = recursive
        recursive.grid(row=4, column=2, sticky="w")
        self._editable.append(recursive)

        ttk.Label(frame, text="覆盖策略").grid(row=5, column=0, sticky="w", pady=4)
        policy_box = ttk.Frame(frame)
        policy_box.grid(row=5, column=1, sticky="w")
        self.policy_radios = []
        for value in ("Skip", "Overwrite"):
            widget = ttk.Radiobutton(policy_box, text=value, variable=self.policy_var, value=value)
            widget.pack(side="left", padx=(0, 12))
            self.policy_radios.append(widget)
            self._editable.append(widget)
        self.warning_label = ttk.Label(
            frame,
            text="注意：仅替换独立输出目录内的目标 SAT/SAB，不会修改源 STEP。",
            foreground="#b00020",
            wraplength=560,
        )
        self.warning_label.grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 4))

        self.advanced_button = ttk.Button(frame, text="高级设置 ▸")
        self.advanced_button.grid(row=7, column=0, columnspan=3, sticky="w", pady=(4, 2))
        self.advanced_frame = ttk.LabelFrame(frame, text="高级设置", padding=8)
        advanced = [
            ("ACIS Version", self.version_var, ("V22", "V23", "V24", "V25", "V26", "V27", "V28", "V29", "V30", "V31")),
            ("Chunk size", self.chunk_var, None),
            ("无响应超时（秒）", self.timeout_var, None),
            ("进程级重试次数", self.retry_var, None),
        ]
        for row, (label, variable, choices) in enumerate(advanced):
            ttk.Label(self.advanced_frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
            if choices:
                widget = ttk.Combobox(self.advanced_frame, textvariable=variable, values=choices, state="readonly", width=12)
            else:
                widget = ttk.Entry(self.advanced_frame, textvariable=variable, width=14)
            widget.grid(row=row, column=1, sticky="w", pady=2)
            self._editable.append(widget)

        self.start_button = ttk.Button(frame, text="开始批量转换")
        self.start_button.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(10, 8))
        self.progress = ttk.Progressbar(frame, variable=self.progress_var, maximum=100.0)
        self.progress.grid(row=10, column=0, columnspan=3, sticky="ew")
        ttk.Label(frame, textvariable=self.progress_text_var).grid(row=11, column=0, columnspan=3, sticky="w")
        ttk.Label(frame, textvariable=self.counts_var).grid(row=12, column=0, columnspan=3, sticky="w")
        ttk.Label(frame, textvariable=self.current_file_var).grid(row=13, column=0, columnspan=3, sticky="w")
        ttk.Label(frame, textvariable=self.process_var).grid(row=14, column=0, columnspan=3, sticky="w")
        ttk.Label(frame, textvariable=self.message_var, wraplength=650).grid(row=15, column=0, columnspan=3, sticky="w")
        ttk.Label(frame, textvariable=self.paths_var, wraplength=650).grid(row=16, column=0, columnspan=3, sticky="w")
        self.events_text = scrolledtext.ScrolledText(frame, height=8, wrap="word", state="disabled")
        self.events_text.grid(row=17, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
        ttk.Label(frame, textvariable=self.release_var, wraplength=650).grid(row=18, column=0, columnspan=3, sticky="w", pady=(6, 0))
        frame.rowconfigure(17, weight=1)
        self.update_overwrite_warning()

    def configure_release(self, release, version_changed: bool) -> None:
        for widget in self._editable:
            if isinstance(widget, ttk.Combobox) and str(widget.cget("textvariable")) == str(self.version_var):
                widget.configure(values=release.acis_versions)
        note = release.output_note
        if version_changed:
            note += " 已将不适用的历史设置改为 {}，请确认后开始转换。".format(release.default_acis_version)
        self.release_var.set(note)

    def _folder_row(self, parent, row, label, variable) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", padx=(0, 6), pady=4)
        button = ttk.Button(parent, text="选择", command=lambda: self._choose_folder(variable))
        button.grid(row=row, column=2, sticky="ew", pady=4)
        self._editable.extend([entry, button])

    def _choose_folder(self, variable) -> None:
        selected = filedialog.askdirectory(initialdir=variable.get() or None)
        if selected:
            variable.set(selected)

    def choose_step_files(self) -> None:
        if not self._controls_enabled:
            return
        selected = filedialog.askopenfilenames(
            parent=self.root,
            title="点选要转换的 STP/STEP 文件（Ctrl/Shift 可多选）",
            initialdir=self.input_var.get() or None,
            filetypes=[("STEP 模型", ("*.stp", "*.step", "*.STP", "*.STEP"))],
        )
        if not selected:
            return
        root = Path(selected[0]).resolve().parent
        try:
            files = tuple(validate_selected_files(root, (Path(path) for path in selected)))
        except (OSError, DiscoveryError) as error:
            self.show_error(str(error))
            return
        self.input_var.set(str(root))
        self._selected_files = files
        self.selection_var.set("仅转换已选的 {} 个文件".format(len(files)))
        self.selected_text.configure(state="normal")
        self.selected_text.delete("1.0", "end")
        self.selected_text.insert("1.0", "\n".join(path.name for path in files))
        self.selected_text.configure(state="disabled")
        self.selected_text.grid()
        self.recursive_check.configure(state="disabled")

    def clear_file_selection(self) -> None:
        if not self._controls_enabled:
            return
        self._selected_files = None
        self.selection_var.set("文件夹模式：扫描 STP/STEP")
        self.selected_text.grid_remove()
        self.recursive_check.configure(state="normal")

    def get_selected_files(self) -> tuple[Path, ...] | None:
        return self._selected_files

    def get_form_values(self) -> GuiFormValues:
        return GuiFormValues(
            input_dir=self.input_var.get(),
            output_dir=self.output_var.get(),
            output_format=self.format_var.get(),
            recursive=bool(self.recursive_var.get()),
            overwrite_policy=self.policy_var.get(),
            acis_version=self.version_var.get(),
            chunk_size=int(self.chunk_var.get()),
            timeout_seconds=float(self.timeout_var.get()),
            retry_count=int(self.retry_var.get()),
        )

    def set_controls_enabled(self, enabled: bool) -> None:
        self._controls_enabled = enabled
        for widget in self._editable:
            if isinstance(widget, ttk.Combobox):
                widget.configure(state="readonly" if enabled else "disabled")
            else:
                widget.configure(state="normal" if enabled else "disabled")
        self.start_button.configure(state="normal" if enabled else "disabled")
        if self._selected_files is not None:
            self.recursive_check.configure(state="disabled")

    def show_error(self, message: str) -> None:
        messagebox.showerror("STEP → ACIS", message, parent=self.root)

    def toggle_advanced(self) -> None:
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced_frame.grid(row=8, column=0, columnspan=3, sticky="ew")
            self.advanced_button.configure(text="高级设置 ▾")
        else:
            self.advanced_frame.grid_remove()
            self.advanced_button.configure(text="高级设置 ▸")

    def update_overwrite_warning(self) -> None:
        if self.policy_var.get() == "Overwrite":
            self.warning_label.grid()
        else:
            self.warning_label.grid_remove()

    def update_state(self, state: GuiRunState) -> None:
        percentage = 100.0 if state.total == 0 else state.completed * 100.0 / state.total
        self.progress_var.set(percentage)
        self.progress_text_var.set(
            "{} / {}  ({:.2f}%)".format(state.completed, state.total, percentage)
        )
        self.counts_var.set(
            "成功 {}    失败 {}    跳过 {}".format(
                state.success,
                state.failed,
                state.skipped,
            )
        )
        self.current_file_var.set("当前文件：{}".format(state.current_file or "—"))
        self.process_var.set(
            "PID / Chunk：{} / {}".format(
                state.pid if state.pid is not None else "—",
                state.chunk_id or "—",
            )
        )
        if state.message:
            self.message_var.set(state.message)
        elif state.running:
            self.message_var.set("运行中")
        else:
            self.message_var.set("就绪")
        self.paths_var.set(
            "CSV：{}    TXT：{}".format(state.csv_path or "—", state.run_log_path or "—")
        )

    def append_event(self, event: GuiEvent) -> None:
        self.events_text.configure(state="normal")
        self.events_text.insert("end", "{}: {}\n".format(event.kind, dict(event.payload)))
        self.events_text.see("end")
        self.events_text.configure(state="disabled")


def main() -> int:
    root_dir = Path(__file__).resolve().parents[2]
    from .spaceclaim_installations import validate_manual_selection
    config = load_config(root_dir / "converter_config.json")
    candidate = validate_manual_selection(config.spaceclaim_exe)
    if candidate.eligibility != "eligible":
        raise ValueError(candidate.reason)
    root = tk.Tk()
    root.title("STEP to ACIS Converter")
    gui = ConverterGui(
        root,
        config_path=root_dir / "converter_config.json",
        capability_profile_path=root_dir / "spaceclaim_cli_profile.json",
        settings_path=default_settings_path(),
        api_version=candidate.release.api_version,
    )
    gui.poll_events()
    root.mainloop()
    return 0
