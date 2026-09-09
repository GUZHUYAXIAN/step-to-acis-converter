# Python Script, API Version = V22
from __future__ import print_function

import io
import json
import os
import sys

try:
    from SpaceClaim.Api.V22 import AcisVersion as V22AcisVersion
except ImportError:
    V22AcisVersion = None


SENTINEL_PATH = None


try:
    string_types = (basestring,)
except NameError:
    string_types = (str,)


def primitive_value(value):
    if isinstance(value, string_types):
        return value
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return None


def collect_argument_globals():
    found = {}
    for name, value in globals().items():
        if "arg" not in name.lower():
            continue
        primitive = primitive_value(value)
        if primitive is not None:
            found[name] = primitive
    return found


def collect_interesting_global_names():
    fragments = ("api", "version", "script", "arg")
    names = []
    for name in globals().keys():
        lowered = name.lower()
        if any(fragment in lowered for fragment in fragments):
            names.append(name)
    return sorted(names)


def probe_v22_host_symbols():
    symbols = {}
    try:
        symbols["DocumentOpen.Execute"] = DocumentOpen.Execute is not None
    except Exception:
        symbols["DocumentOpen.Execute"] = False
    try:
        symbols["DocumentSave.Execute"] = DocumentSave.Execute is not None
    except Exception:
        symbols["DocumentSave.Execute"] = False
    try:
        symbols["ExportOptions.Create"] = ExportOptions.Create is not None
    except Exception:
        symbols["ExportOptions.Create"] = False
    try:
        symbols["AcisVersion.V22"] = (
            V22AcisVersion is not None and V22AcisVersion.V22 is not None
        )
    except Exception:
        symbols["AcisVersion.V22"] = False
    return symbols


def main():
    if not SENTINEL_PATH:
        raise RuntimeError("SENTINEL_PATH was not specialized")
    host_symbols = probe_v22_host_symbols()
    payload = {
        "probe_schema": 1,
        "script_executed": True,
        "api_expected": "V22",
        "host_api_verified": all(host_symbols.values()),
        "host_api_symbols": host_symbols,
        "process_id": os.getpid(),
        "sys_argv": list(sys.argv),
        "candidate_script_args": collect_argument_globals(),
        "globals_of_interest": collect_interesting_global_names(),
        "unicode_round_trip": "中文 path with spaces",
    }
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2)
    with io.open(SENTINEL_PATH, "w", encoding="utf-8") as sentinel_file:
        sentinel_file.write(serialized)
        sentinel_file.flush()
    print("SPACECLAIM_V22_PROBE_OUTPUT")


main()
