---
status: pending
priority: p3
issue_id: "004"
tags: [code-review, python, architecture, refactor]
dependencies: []
---

# Refactor to package structure with typer CLI (after Phase 1 works)

## Problem Statement

The plan organizes Python as 5 standalone scripts + `_common.py`. Kieran
notes this is "bash-thinking" — a real Python package with a CLI is
more testable, importable, and removes path-juggling.

## Findings

- **Source:** kieran-python-reviewer (Finding #3).
- This is a P3, not a P2 — 5 scripts work fine for v1, and the refactor
  is busywork if it happens before the scripts are validated end-to-end.
- The right time to apply this is *after* Phase 1 produces a working
  CSV, when the script interfaces are settled.

## Proposed Solution

```
src/weekly_movers/
  __init__.py
  __main__.py           # python -m weekly_movers <subcommand>
  paths.py              # Pydantic-validated path config
  clock.py              # ET trading-day logic
  ingest/
    __init__.py
    universe.py
    prices.py
  screens/
    __init__.py
    compute.py
  render/
    __init__.py
    site.py
    narrative.py
  cli.py                # typer subcommands
pyproject.toml          # ruff, mypy --strict, pytest
tests/
  test_compute.py
  test_render.py
```

Use `typer` for `python -m weekly_movers fetch-prices --chunk-size 80`.
Workflow yml updates: `python -m weekly_movers fetch-prices` instead
of `python scripts/fetch_prices.py`.

## Recommended Action

(Defer until Phase 1 verification gate is reached.)

## Acceptance Criteria

- [ ] All logic moved from `scripts/` into `src/weekly_movers/`
- [ ] `python -m weekly_movers --help` shows all subcommands
- [ ] `pytest tests/` runs at least one test per module
- [ ] `mypy --strict src/` passes
- [ ] `ruff check` passes
- [ ] CI workflow yml updated; same end-to-end behavior

## Work Log

(empty — deferred until Phase 1 done)

## Resources

- typer: https://typer.tiangolo.com/
- pyproject.toml + ruff: https://docs.astral.sh/ruff/
