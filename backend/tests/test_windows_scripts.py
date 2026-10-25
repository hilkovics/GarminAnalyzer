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
