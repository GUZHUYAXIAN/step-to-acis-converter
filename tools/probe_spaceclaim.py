import argparse
from datetime import datetime
import os
from pathlib import Path
import sys

from step_to_acis.probe_service import run_model_free_probe
from step_to_acis.runtime_paths import RuntimePaths
from step_to_acis.spaceclaim_installations import validate_manual_selection


def build_parser():
    parser = argparse.ArgumentParser(
        description="Verify the local SpaceClaim 2022 R2 / 2026 R1 Headless contract"
    )
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--run-root", type=Path)
    return parser


def default_run_root():
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "StepToAcis" / "probe-runs"
    return Path.cwd() / ".validation" / "probe-runs"


def create_run_directory(root):
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_directory = root.resolve() / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    return run_directory


def main(argv=None):
    arguments = build_parser().parse_args(argv)
    if not arguments.exe.is_file():
        print(
            "SpaceClaim executable does not exist: {}".format(arguments.exe),
            file=sys.stderr,
        )
        return 2
    if arguments.timeout <= 0:
        print("timeout must be greater than zero", file=sys.stderr)
        return 2

    candidate = validate_manual_selection(arguments.exe)
    if candidate.eligibility != "eligible":
        print(candidate.reason, file=sys.stderr)
        return 2
    root = (arguments.run_root or default_run_root()).resolve()
    resources = Path(__file__).resolve().parents[1] / "spaceclaim"
    paths = RuntimePaths(resources, root, root, root / "profiles", root / "runs", root / "gui.json")
    print("Probing {} ...".format(candidate.release.label), flush=True)
    outcome = run_model_free_probe(candidate, paths, timeout_seconds=arguments.timeout)
    print("{}: {}".format("PASS" if outcome.passed else "FAIL", outcome.reason))
    print("Probe report: {}".format(outcome.report_path))
    if outcome.profile_path:
        print("Use --capability-profile {} for CLI conversion".format(outcome.profile_path))
    return 0 if outcome.passed else 3


if __name__ == "__main__":
    raise SystemExit(main())
