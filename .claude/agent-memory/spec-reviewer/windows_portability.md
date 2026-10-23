---
name: windows-portability
description: Checklist for Windows (cp1250 locale, backslash paths) portability reviews - encoding, SQLite URLs, alembic %, line endings
metadata:
  type: project
---

The user runs the suite on Windows 11 (default encoding cp1250, core.autocrlf=true, no .gitattributes as of 2026-10-23).
`uv` is not on the Git Bash PATH; use `C:/Users/hilko/GarminAnalyzer/.venv/Scripts/python.exe` for scratch checks.

**Why:** the 2026-10-23 Windows fix added encoding="utf-8" and `.as_posix()` SQLite URLs; the same class of bug
reappears in every new file read/write.

**How to apply:** on every review grep backend/, scripts/, ui-streamlit/ for read_text/write_text/open( without
encoding=. Also check:
- pydantic-settings `env_file=".env"` without `env_file_encoding="utf-8"` (decoded with the locale).
- Alembic `set_main_option` goes through configparser interpolation: a '%' in the DB path raises ValueError
  (session.migrate and alembic/env.py); needs `.replace("%", "%%")`.
- Generated artifacts (docs/openapi.json, API.md, fixtures) are written in text mode -> CRLF on Windows;
  only autocrlf keeps the repo LF. Suggest newline="\n" or a .gitattributes.
