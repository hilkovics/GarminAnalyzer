"""Keep Windows from going back to sleep while the morning run works (no-op on other systems).

Task Scheduler wakes the PC from sleep at the run time (WakeToRun); Windows then sleeps again after about two
minutes without user input ("unattended sleep"), which could cut a sync in half. During the run the process
asks the system to stay awake (SetThreadExecutionState); afterwards the normal power settings apply again.
"""

import contextlib
import logging
import sys
from collections.abc import Iterator

log = logging.getLogger(__name__)

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def _kernel32():  # type: ignore[no-untyped-def]  # patched in tests
    import ctypes

    return ctypes.windll.kernel32  # type: ignore[attr-defined]


@contextlib.contextmanager
def keep_awake() -> Iterator[None]:
    """System stays awake inside the block (Windows only); never raises because of the power API."""
    if sys.platform != "win32":
        yield
        return
    try:
        kernel32 = _kernel32()
        kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    except Exception:  # an exotic Windows without the call: run anyway
        log.warning("could not ask Windows to stay awake during the morning run", exc_info=True)
        yield
        return
    try:
        yield
    finally:
        kernel32.SetThreadExecutionState(ES_CONTINUOUS)
