import json
from pathlib import Path
import sys
import tempfile
import threading
import tkinter as tk

from step_to_acis.batch_service import BatchRequest, run_batch
from step_to_acis.gui import ConverterGui
from step_to_acis.probe_runner import CliCapabilityProfile
from step_to_acis.supervisor import BatchSupervisor


def prepare_fake_workspace(workspace: Path) -> dict[str, object]:
    input_dir = workspace / "中文 STEP 输入"
    output_dir = workspace / "中文 ACIS 输出"
    input_dir.mkdir(parents=True, exist_ok=True)
    executable = workspace / "Fake SpaceClaim.exe"
    executable.write_bytes(b"fake executable")
    sources = [
        input_dir / "A 中文 success.stp",
        input_dir / "B failed.step",
        input_dir / "C success.STP",
    ]
    for source, mode in zip(sources, ("success", "failed", "success")):
        source.write_text("MODE:{}".format(mode), encoding="utf-8")
    config_path = workspace / "fake_converter_config.json"
    config_path.write_text(
        json.dumps(
            {
                "spaceclaim_exe": str(executable),
                "input_dir": str(input_dir),
                "output_dir": str(output_dir),
                "recursive": False,
                "output_formats": ["SAB"],
                "overwrite_policy": "Skip",
                "acis_version": "V22",
                "acis_units": "Millimeters",
                "chunk_size": 3,
                "heartbeat_timeout_seconds": 5,
                "retry_count": 0,
                "preserve_relative_directories": True,
                "long_path_warning_threshold": 240,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "input_dir": input_dir,
        "output_dir": output_dir,
        "sources": tuple(sources),
        "config_path": config_path,
        "profile_path": workspace / "unused_fake_profile.json",
        "settings_path": workspace / "gui_settings.json",
    }


def run_fake_request(request: BatchRequest, reporter):
    fake_worker = Path(__file__).resolve().with_name("fake_spaceclaim.py")

    def supervisor_factory(**kwargs):
        return BatchSupervisor(
            config=kwargs["config"],
            run_directory=kwargs["run_directory"],
            worker_template=fake_worker,
            command_factory=lambda worker, script_output: [sys.executable, str(worker)],
            poll_interval_seconds=0.02,
            status_callback=kwargs["status_callback"],
        )

    profile = CliCapabilityProfile(
        run_script=True,
        script_api_v22=True,
        exit_after_script=True,
        headless=True,
        script_args=False,
        script_output=True,
        script_args_strategy="specialized_worker_literal",
    )
    return run_batch(
        request,
        reporter,
        capability_profile_loader=lambda path, config: profile,
        supervisor_factory=supervisor_factory,
    )


def run_fake_batch(workspace: Path, reporter):
    config_path = workspace / "fake_converter_config.json"
    if not config_path.is_file():
        prepare_fake_workspace(workspace)
    return run_fake_request(
        BatchRequest(
            config_path=config_path,
            overrides={},
            capability_profile_path=workspace / "unused_fake_profile.json",
        ),
        reporter,
    )


def build_fake_gui(
    root: tk.Tk,
    workspace: Path,
    *,
    view_factory=None,
    thread_factory=threading.Thread,
) -> ConverterGui:
    paths = prepare_fake_workspace(workspace)

    def fake_runner(request, reporter):
        return run_fake_request(request, reporter)

    return ConverterGui(
        root,
        config_path=paths["config_path"],
        capability_profile_path=paths["profile_path"],
        settings_path=paths["settings_path"],
        batch_runner=fake_runner,
        thread_factory=thread_factory,
        view_factory=view_factory,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="step-to-acis-gui-fake-") as temporary_directory:
        root = tk.Tk()
        root.title("STEP to ACIS Converter (Fake Smoke)")
        gui = build_fake_gui(root, Path(temporary_directory) / "中文 fake workspace")
        gui.poll_events()
        root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
