"""keep_awake: Windows asks to stay awake during the run and releases it afterwards; elsewhere a no-op."""

import pytest

from training import keep_awake as mod


class FakeKernel32:
    def __init__(self):
        self.calls: list[int] = []

    def SetThreadExecutionState(self, flags: int) -> int:
        self.calls.append(flags)
        return 1


def test_windows_stays_awake_and_releases_even_on_error(monkeypatch):
    fake = FakeKernel32()
    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_kernel32", lambda: fake)
    with pytest.raises(RuntimeError), mod.keep_awake():
        assert fake.calls == [mod.ES_CONTINUOUS | mod.ES_SYSTEM_REQUIRED]
        raise RuntimeError("sync failed")
    assert fake.calls[-1] == mod.ES_CONTINUOUS


def test_missing_power_api_does_not_stop_the_run(monkeypatch):
    def broken():
        raise OSError("no kernel32")

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_kernel32", broken)
    ran = []
    with mod.keep_awake():
        ran.append(True)
    assert ran == [True]


def test_other_systems_do_nothing(monkeypatch):
    monkeypatch.setattr(mod.sys, "platform", "linux")
    monkeypatch.setattr(mod, "_kernel32", lambda: pytest.fail("must not touch the Win32 API"))
    with mod.keep_awake():
        pass
