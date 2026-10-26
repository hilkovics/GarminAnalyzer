"""Windows helper scripts: encoding Windows PowerShell 5.1 reads correctly, and the files they reference."""

from training.config import PROJECT_ROOT

SCRIPTS = PROJECT_ROOT / "scripts"
BOM = b"\xef\xbb\xbf"


def test_non_ascii_powershell_scripts_carry_a_utf8_bom():
    # Without a BOM, Windows PowerShell 5.1 decodes a script in the ANSI code page and garbles "Spánok".
    for script in SCRIPTS.glob("*.ps1"):
        raw = script.read_bytes()
        if any(b > 127 for b in raw.removeprefix(BOM)):
            assert raw.startswith(BOM), script.name


def test_shortcut_points_at_existing_files():
    text = (SCRIPTS / "install_shortcut_windows.ps1").read_text(encoding="utf-8-sig")
    assert "start_app.ps1" in text and "assets\\app.ico" in text
    assert (SCRIPTS / "start_app.ps1").is_file()
    icon = (SCRIPTS / "assets" / "app.ico").read_bytes()
    assert icon[:4] == b"\x00\x00\x01\x00" and int.from_bytes(icon[4:6], "little") >= 3  # ICO with ≥ 3 sizes


def test_launcher_keeps_the_server_local():
    text = (SCRIPTS / "start_app.ps1").read_text(encoding="utf-8-sig")
    assert "http://127.0.0.1:" in text and "--host" not in text  # `training api` binds 127.0.0.1 by default


def test_move_to_server_hands_over_the_morning_run():
    text = (SCRIPTS / "move_to_server.ps1").read_text(encoding="utf-8-sig")
    # the WAL is folded in before copying, the Windows task is removed so only the server pushes to Garmin
    assert "wal_checkpoint(TRUNCATE)" in text and 'start_app.ps1") -Stop' in text
    assert 'install_task_windows.ps1") -Remove' in text
    assert "-Force" in text and "garmin_tokens.json" in text
    shortcut = (SCRIPTS / "install_shortcut_windows.ps1").read_text(encoding="utf-8-sig")
    assert "--app=$Url" in shortcut


def test_morning_task_wakes_the_pc_and_runs_without_sign_in():
    text = (SCRIPTS / "install_task_windows.ps1").read_text(encoding="utf-8-sig")
    assert '[string]$At = "09:00"' in text
    assert "-WakeToRun" in text and "RTCWAKE 1" in text  # wake from sleep, wake timers allowed
    assert "-LogonType S4U" in text and "-Verb RunAs" in text  # no sign-in needed, one UAC prompt
    assert "-InteractiveOnly" in text  # the old behaviour stays available without admin rights
    # repeats hourly for 4 h; --once-per-day makes the repeats after a complete run no-ops (METRICS §11.2)
    assert "-RepetitionInterval (New-TimeSpan -Hours 1)" in text
    assert "-RepetitionDuration (New-TimeSpan -Hours 4)" in text
    assert "training morning --once-per-day" in text
