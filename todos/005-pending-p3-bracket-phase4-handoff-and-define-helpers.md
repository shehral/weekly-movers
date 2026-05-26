---
status: pending
priority: p3
issue_id: "005"
tags: [code-review, agent-native, phase-4]
dependencies: []
---

# Bracket Phase 4 human-vs-agent handoff; define `pivot_to_long`; pre-decide deferred questions

## Problem Statement

Three minor gaps that block fully-autonomous execution by an agent:

1. **Phase 4 "Routine setup" mixes things only the human can do** (PAT
   creation at github.com/settings/tokens, registering env vars in
   Claude routine UI) with things an agent can write (the
   `pat-expiry-check.yml` workflow, the routine script template).
   Currently one numbered list; needs an explicit "agent stops here,
   user takes over" split.

2. **`pivot_to_long` helper is referenced in the Phase 1 snippet but
   never defined.** Agent must invent the implementation. Add a
   5-line definition inline.

3. **"Consider / evaluate" decisions left open:**
   - `noindex` meta tag (Frontend Design Tokens section) — yes or no?
   - Custom domain CNAME (Phase 5) — defer or not?
   - `requirements.txt` lower-bound pins vs lockfile exact pins
     (handled by todo #001)
   - The Phase 1 "Open implementation question" says "Add a comment
     flagging this" but doesn't specify the comment text.

## Findings

- **Source:** agent-native-reviewer (Finding #4 + #5 + minor obs).

## Proposed Solution

### Sub-finding A: Split Phase 4 routine setup

Restructure Phase 4 from a single numbered list to:

```markdown
### Agent tasks (autonomous)

1. Create `.github/workflows/pat-expiry-check.yml`
2. Write `scripts/routines/narrative.sh` (or equivalent — the script
   the Claude routine will run when triggered)
3. Document the routine YAML template in README

### Human required (stop here, user takes over)

1. Create fine-grained PAT at github.com/settings/tokens, scoped to
   `shehral/weekly-movers` only, `contents: write` only, 90-day expiry
2. Register `/schedule` Claude routine via Claude Code CLI:
   - Cron: `30 12 * * 1-5` UTC
   - Env: `GH_TOKEN=<PAT>`, `ANTHROPIC_API_KEY=<key>`
   - Script body: see `scripts/routines/narrative.sh`
3. Test by running the routine manually via `/schedule run weekly-movers-narrative`
```

### Sub-finding B: Define `pivot_to_long`

Add to the Phase 1 snippet:

```python
def pivot_to_long(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance returns wide multi-index columns (ticker, field) ×
    date rows. Pivot to long: (ticker, date) × field."""
    return (df.stack(level=0)               # ticker becomes index level
              .rename_axis(["date", "ticker"])
              .reset_index()
              .rename(columns=str.lower))   # 'Open' → 'open', etc.
```

### Sub-finding C: Pre-decide open questions

Update plan with:

- **`noindex` meta tag:** YES — include `<meta name="robots" content="noindex">`
  on every page. This is a personal screener, not advisory content;
  safe-by-default.
- **Custom domain CNAME:** DEFER to a post-v1 enhancement. Phase 5
  custom-domain bullet stays as "optional".
- **Phase 1 split-comment text:** add inline:
  ```python
  # Note: with auto_adjust=True (yfinance default), historical OHLC
  # is split-adjusted in-place. The dollar-change math
  # |Close[t] - Close[t-5]| reads as small after a split, which is
  # correct — the security genuinely didn't move in the split-adjusted
  # frame. No special handling needed.
  ```

## Recommended Action

(Apply during /ce:work — these are 30 minutes of plan + snippet edits.)

## Acceptance Criteria

- [ ] Phase 4 has explicit "Agent tasks" vs "Human required" subsections
- [ ] `pivot_to_long` is defined in the Phase 1 snippet
- [ ] `noindex` meta tag committed to `templates/base.html.j2`
- [ ] CNAME is explicitly "optional / v2"
- [ ] Phase 1 has the split-comment text inline

## Work Log

(empty)

## Resources

- Plan reference: Phase 4 lines 695-755 (routine setup);
  Phase 1 lines 282-294 (fetch_prices.py spec);
  agent-native-reviewer output above.
