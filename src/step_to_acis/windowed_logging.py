"""Supply writable streams when the Windows windowed bootloader has none."""

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import traceback


@contextmanager
def windowed_streams(state_root: Path):
    original_stdout, original_stderr = sys.stdout, sys.stderr
    if original_stdout is not None and original_stderr is not None:
        yield
        return

    # A read-only state directory must not prevent the self-check from opening.
    log_root = state_root / "logs"
    try:
        log_root.mkdir(parents=True, exist_ok=True)
        stream = _open_log(log_root)
    except OSError:
        log_root = Path(tempfile.gettempdir()) / "SpaceClaimStepToAcis" / "logs"
        log_root.mkdir(parents=True, exist_ok=True)
        stream = _open_log(log_root)
    try:
        if original_stdout is None:
            sys.stdout = stream
        if original_stderr is None:
            sys.stderr = stream
        try:
            yield
        except Exception:
            traceback.print_exc(file=stream)
            raise
    finally:
        sys.stdout, sys.stderr = original_stdout, original_stderr
        stream.close()


def _open_log(root: Path):
    return tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", buffering=1,
        prefix="application-{}-".format(datetime.now().strftime("%Y%m%d-%H%M%S")),
        suffix=".log", dir=root, delete=False,
    )
