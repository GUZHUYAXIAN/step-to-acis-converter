from collections.abc import Callable
import tkinter as tk

from .environment_controller import EnvironmentController
from .environment_gui import EnvironmentCheckGui
from .environment_models import EnvironmentState
from .gui import ConverterGui
from .gui_models import GuiFormValues
from .portable_config import (
    has_accepted_portable_paths,
    mark_portable_paths_accepted,
    portable_paths_marker_path,
    write_portable_config,
)
from .runtime_paths import RuntimePaths, default_runtime_paths, resource_path


def launch_converter(
    root: tk.Tk,
    state: EnvironmentState,
    paths: RuntimePaths,
    *,
    converter_factory: Callable[..., ConverterGui] | None = None,
) -> ConverterGui:
    if (
        not state.can_enter_converter
        or state.selected is None
        or state.profile_path is None
    ):
        raise ValueError("environment self-check has not authorized conversion")

    config_path = paths.state_root / "runtime_config.json"
    write_portable_config(config_path, state.selected.executable)
    marker_path = portable_paths_marker_path(paths)
    factory = converter_factory or ConverterGui
    return factory(
        root,
        config_path=config_path,
        capability_profile_path=state.profile_path,
        settings_path=paths.gui_settings_path,
        worker_template_path=resource_path("worker_v22.py", root=paths.resource_root),
        defaults=GuiFormValues(input_dir="", output_dir=""),
        restore_saved_paths=has_accepted_portable_paths(marker_path),
        on_settings_saved=lambda: mark_portable_paths_accepted(marker_path),
    )


def main() -> int:
    root = tk.Tk()
    root.title("STEP → ACIS 环境自检")
    paths = default_runtime_paths()
    controller = EnvironmentController(paths)
    holder = {}

    def approved(state: EnvironmentState) -> None:
        holder["self_check"].destroy()
        root.title("STEP to ACIS Converter")
        converter = launch_converter(root, state, paths)
        holder["converter"] = converter
        converter.poll_events()

    self_check = EnvironmentCheckGui(
        root,
        controller=controller,
        on_approved=approved,
    )
    holder["self_check"] = self_check
    self_check.rescan()
    self_check.poll_events()
    root.mainloop()
    return 0
