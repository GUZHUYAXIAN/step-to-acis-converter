from dataclasses import asdict, fields, replace
import json
import os
from pathlib import Path
from collections.abc import Mapping

from .gui_models import GuiFormValues, GuiInputError, validate_form_values


_FIELD_NAMES = tuple(field.name for field in fields(GuiFormValues))


def default_settings_path(environ: Mapping[str, str] | None = None) -> Path:
    environment = os.environ if environ is None else environ
    local_app_data = environment.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "SpaceClaimStepToAcis" / "gui_settings.json"


def load_gui_settings(
    path: Path,
    defaults: GuiFormValues,
    *,
    restore_paths: bool = True,
) -> GuiFormValues:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return defaults
    if not isinstance(payload, dict):
        return defaults

    loaded = defaults
    path_fields = ("input_dir", "output_dir")
    if restore_paths:
        saved_paths = {
            field_name: payload[field_name]
            for field_name in path_fields
            if field_name in payload
        }
        try:
            loaded = validate_form_values(replace(defaults, **saved_paths))
        except GuiInputError:
            for field_name in path_fields:
                if field_name not in payload:
                    continue
                candidate = replace(loaded, **{field_name: payload[field_name]})
                try:
                    loaded = validate_form_values(candidate)
                except GuiInputError:
                    continue

    for field_name in _FIELD_NAMES:
        if field_name in path_fields or field_name not in payload:
            continue
        candidate = replace(loaded, **{field_name: payload[field_name]})
        probe = candidate
        try:
            validate_form_values(probe)
        except GuiInputError as error:
            if "input_dir" not in str(error) and "output_dir" not in str(error):
                continue
            probe = replace(
                candidate,
                input_dir="__portable_input__",
                output_dir="__portable_output__",
            )
            try:
                validate_form_values(probe)
            except GuiInputError:
                continue
        loaded = candidate
    return loaded

def save_gui_settings(path: Path, values: GuiFormValues) -> None:
    validated = validate_form_values(values)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".tmp")
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as settings_file:
            json.dump(asdict(validated), settings_file, ensure_ascii=False, indent=2)
            settings_file.write("\n")
            settings_file.flush()
            os.fsync(settings_file.fileno())
        os.replace(temporary_path, path)
    except Exception:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise
