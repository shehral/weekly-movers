---
status: pending
priority: p2
issue_id: "001"
tags: [code-review, dependencies, supply-chain, agent-native]
dependencies: []
---

# Pin versions and generate `requirements.lock` with hashes

## Problem Statement

The plan workflow runs `pip install --require-hashes -r requirements.lock`
and the Operational Playbook checks for it, but no phase tells you *how*
to generate the lockfile or which `yfinance` version to pin to. An agent
dispatched via `/ce:work` cannot resolve this autonomously.

Also: `requirements.txt` still has lower-bound pins (`yfinance>=0.2.50`)
which is incompatible with a hash-locked install.

## Findings

- **Source:** agent-native-reviewer (Finding #1).
- The CI workflow will error on first run if `requirements.lock` is
  missing.
- The lower-bound vs exact-pin mismatch is the kind of thing that "works
  on my machine" passes through local-dev and fails in CI.
- `yfinance` cycles fast; without a pin, the daily refresh is at the
  mercy of upstream changes that could change OHLC schema or break
  `curl_cffi` integration.

## Proposed Solutions

### Option A — `uv pip compile --generate-hashes` (Recommended)

```bash
uv pip compile --generate-hashes requirements.txt -o requirements.lock
```

**Pros:** uv is fast, generates a deterministic lockfile with SHA256
hashes. Modern (2025-2026) tooling.

**Cons:** Adds `uv` as a build-time dep (already in Shehral's
workflow per CLAUDE.md, so neutral).

**Effort:** Small (one command + commit).

### Option B — `pip-tools` (`pip-compile`)

```bash
pip-compile --generate-hashes requirements.txt -o requirements.lock
```

**Pros:** Long-standing, well-known tooling.

**Cons:** Slower than uv; less momentum in 2026.

**Effort:** Small.

## Recommended Action

(Filled during /ce:work execution — likely Option A.)

## Technical Details

**Affected files:**
- `requirements.txt` — switch all lower-bound `>=` to exact `==`
- `requirements.lock` (new) — generated, committed
- `.github/workflows/refresh-data.yml` — already references the lock
- `Phase 1` plan description — add the compile step

**`requirements.txt` after change:**
```
yfinance==0.2.52         # or whichever resolves at compile time
pandas==2.2.3
pyarrow==15.0.2
pandas_market_calendars==4.4.2
jinja2==3.1.4
requests==2.32.3
markdown-it-py==3.0.0
anthropic==0.42.0
bleach==6.2.0
curl_cffi==0.7.4
tenacity==9.0.0          # added per kieran-python
```

## Acceptance Criteria

- [ ] `requirements.lock` exists in repo root with `--hash=sha256:...`
      lines for every dep + transitive dep
- [ ] `pip install --require-hashes -r requirements.lock` completes
      cleanly on `ubuntu-latest` in CI
- [ ] `requirements.txt` no longer contains `>=` pins
- [ ] Plan Phase 1 documents the regeneration step (Mondays alongside
      universe refresh, or quarterly — pick one)

## Work Log

(empty — start during /ce:work)

## Resources

- uv pip compile docs: https://docs.astral.sh/uv/pip/compile/
- pip-tools: https://github.com/jazzband/pip-tools
- Plan reference: lines 595-596 (workflow), 1184 (playbook check)
