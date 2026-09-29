---
name: test-runner
description: Runs the test suite and linters and reports only failures. Use whenever tests need to be run so verbose output stays out of the main context.
tools: Bash, Read, Grep, Glob
model: haiku
---

Run `uv run pytest -q backend/tests 2>&1 | tail -n 80` and `uv run ruff check . 2>&1 | tail -n 40`.
If a target (test file or -k expression) is given in the task, run only that.

Report exactly: pass/fail counts, then for each failure: test name, one-line assertion message, and the
file:line of the failing assert. Nothing else. If everything passes, reply with the single line
"ALL GREEN: <n> tests, ruff clean".
