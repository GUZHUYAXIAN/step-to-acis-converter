# -*- coding: utf-8 -*-
# Python Script, API Version = V261
from __future__ import print_function
import io
import json
import os
import sys

SENTINEL_PATH = None


def main():
    if not SENTINEL_PATH:
        raise RuntimeError("SENTINEL_PATH was not specialized")
    symbols = {}
    error = ""
    try:
        from SpaceClaim.Api.V261 import AcisUnits, ExportOptions, Window
        from SpaceClaim.Api.V261.Scripting.Commands import DocumentOpen, DocumentSave
        symbols["DocumentOpen.Execute"] = DocumentOpen.Execute is not None
        symbols["DocumentSave.Execute"] = DocumentSave.Execute is not None
        symbols["Window.Close"] = Window.Close is not None
        options = ExportOptions.Create()
        options.Acis.Units = AcisUnits.Millimeters
        symbols["AcisUnits.Millimeters"] = options.Acis.Units == AcisUnits.Millimeters
    except Exception as exception:
        error = str(exception)
    payload = {
        "probe_schema": 1,
        "script_executed": True,
        "api_expected": "V261",
        "host_api_verified": len(symbols) == 4 and all(symbols.values()),
        "host_api_symbols": symbols,
        "error": error,
        "process_id": os.getpid(),
        "sys_argv": list(sys.argv),
        "candidate_script_args": {},
        "globals_of_interest": [],
        "unicode_round_trip": u"\u4e2d\u6587 path with spaces",
    }
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2)
    if not isinstance(serialized, type(u"")):
        serialized = serialized.decode("utf-8")
    with io.open(SENTINEL_PATH, "w", encoding="utf-8") as sentinel_file:
        sentinel_file.write(serialized)
        sentinel_file.flush()
    print("SPACECLAIM_V261_PROBE_OUTPUT")


main()
