---
status: pending
priority: p3
issue_id: "007"
tags: [code-review, github-actions, deprecation]
dependencies: []
---

# Bump GH Actions checkout + setup-python to Node 24-compatible versions

## Problem Statement

First workflow run on 2026-05-26 produced one annotation:

> Node.js 20 actions are deprecated. `actions/checkout@v4`,
> `actions/setup-python@v5` are running on Node.js 20. Actions will be
> forced to run with Node.js 24 by default starting June 2nd, 2026.

Currently informational — workflow still runs. Will become a hard
failure after the cutoff if the actions haven't been updated.

## Findings

- **Source:** GH Actions runner annotation on run 26465080314.
- Two affected steps:
  - `actions/checkout@v4`
  - `actions/setup-python@v5`

## Proposed Solution

Check for newer major versions of both actions that support Node 24,
upgrade in `.github/workflows/refresh-data.yml`. Likely just bumping
the version pin once GitHub releases the updated action.

Alternative (temporary): set `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true`
env to opt in early. Riskier — Node 24 might surface other action bugs.

## Recommended Action

Wait until ~mid-May 2026 (a couple weeks before the June 2 cutoff),
check for action updates, bump pins, validate one workflow_dispatch run.

## Acceptance Criteria

- [ ] `actions/checkout@v5` or later (or @v4 with Node 24 support)
- [ ] `actions/setup-python@v6` or later
- [ ] No Node 20 deprecation annotation on next run

## Resources

- https://github.blog/changelog/2025-09-19-deprecation-of-node-20-on-github-actions-runners/
