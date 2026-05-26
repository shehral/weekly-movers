---
status: complete
priority: p1
issue_id: "006"
tags: [code-review, yfinance, reliability, blocker, phase-3, resolved-by-provider-switch]
dependencies: []
resolved_date: 2026-05-26
---

## Resolution (2026-05-26)

**Resolved by switching screen data source to Polygon.io Grouped Daily
Bars.** New `scripts/_polygon.py` adapter built; `scripts/fetch_prices.py`
refactored. Full-universe re-validation:

- **6,478 / 6,509 tickers covered (99.5%)** — vs 21% with yfinance batch
- **~7 min runtime** for 35 trading days of history (35 API calls @
  12.5s sleep on free tier 5 calls/min limit)
- **561 names in screen output** (139 Bucket A + 422 Bucket B)
- One day failed (today's 2026-05-26 — 429 on last call after burning
  the per-minute budget); harmless since 34 days is still > 30 needed
  for avg-volume calc.

yfinance is retained for Phase 2 chart-history pulls where the
~500-ticker subset stays well under the 1,300-ticker rate-limit wall.

Plan updates: Phase 1 fetch_prices.py spec, Phase 3 workflow yml (env
`POLYGON_API_KEY`), Risk Analysis table (yfinance row demoted to
chart-only impact). Original analysis below for reference.

---

# Mitigate yfinance rate-limiting before Phase 3 deploy

## Problem Statement

Full-universe fetch on 2026-05-25 (6,509 tickers, 80-chunk + 2s sleep +
`curl_cffi` chrome impersonation + tenacity retries) saw **5,165 tickers
(79%) fail** with `YFRateLimitError('Too Many Requests')`. Pattern: the
first ~16 chunks (alphabetical A through T) succeeded; chunks 17+ (V-Z)
all failed; tenacity retries did not recover within the run.

**This is a hard blocker for Phase 3** (GH Actions cron deploy). The
cron will reliably reproduce this failure pattern every day with the
current code.

The Phase 1 screen *output* is still useful on the partial data (126
names produced, all valid), so the pipeline degrades gracefully — but
relying on degradation is not a strategy.

## Findings

- **Run output:** `data/cache/2026-05-26.parquet` (300,749 rows for
  ~1,344 tickers; expected ~1.6M rows for all 6,509).
- **Failure mode:** Yahoo's per-IP rate limiter trips after ~1,300
  ticker requests in close succession. Once tripped, the IP is
  blocked for a (probably) multi-minute window. `curl_cffi` chrome
  TLS fingerprinting did NOT bypass this — the limiter is request-rate
  based, not fingerprint based.
- **Observed runtime to failure:** ~4 minutes (vs. ~10 min expected
  for full success).
- **Confirms the best-practices-researcher's 2025-2026 warning** (see
  yfinance issues #2422, #2614, #2633). The plan's deepen-step
  research called this exactly.

## Proposed Solutions

### Option A — Split fetch into 2 jobs at different times (Recommended)

Two GH Actions jobs at 11:30 UTC and 11:50 UTC, each fetching half
the universe. Yahoo's window resets in the 20-min gap. Total wall time
~5 min per job; combined coverage approaches 100%.

Implementation: `fetch_prices.py --slice 0/2` and `--slice 1/2` flags
that take alphabetical slices. Two workflow jobs, second `needs: [first]`
with a 15-min wait step OR two separate cron entries.

**Pros:** Clean, no new infrastructure, predictable.

**Cons:** Doubles workflow complexity. Two commits per day (or one
commit after both finish).

**Effort:** Small (~30 min of plumbing).

### Option B — Slower fetch: 40-ticker chunks + 5s sleep

Halve chunk size, 2.5x the sleep. 6,509/40 = 163 chunks × 7s
download + 5s sleep = ~33 min runtime. **Exceeds 30-min workflow
timeout.**

**Pros:** Single-job simplicity.

**Cons:** Likely runs over budget. Still might hit the rate limiter at
1,300-ticker mark.

**Effort:** Trivial config change.

**Verdict:** Probably not viable.

### Option C — Pre-filter universe before full fetch

Single 1-day fetch on all 6,509 tickers (still hits rate limiter,
but smaller payload per request). Filter to price-in-band candidates
(~1,500-2,500 names). Full 1y fetch on candidates only.

**Pros:** Architecturally cleanest — most of universe is irrelevant
(prices outside both bands).

**Cons:** Still has the request-count rate limit; the payload-size
doesn't matter to Yahoo's limiter. Likely doesn't help materially.

**Effort:** Medium (changes fetch_prices to a two-phase pull).

**Verdict:** Try as a fallback if A doesn't pan out.

### Option D — Switch to Financial Modeling Prep (FMP) free tier

Pre-create FMP account, swap data provider. ~250 req/day free; need
batch endpoint coverage. Plan's risk section already names FMP as the
cold backup.

**Pros:** Removes Yahoo dependency permanently.

**Cons:** Free tier rate limits might bite too. Different ticker
universe semantics. Bigger code change.

**Effort:** Medium (new client, schema mapping, fallback wiring).

**Verdict:** Right answer if yfinance breakdown continues. Open the
FMP account NOW as insurance.

### Option E — Cache from yesterday's commit

Daily fetch needs only ~1 new session per ticker if we already have
the prior 250 days from the last commit. Read previous parquet from
the most-recent commit, fetch only today's bar, append.

**Pros:** Slashes fetch volume to ~1 day per ticker (6,509 tickers,
still 6,509 requests but trivial per-request).

**Cons:** Rate limit is per-request not per-byte, so this doesn't
help with the 1,300-ticker wall. First-run problem (no cache).
Schema/repair complexity (corporate actions invalidate prior data).

**Verdict:** Not the right answer for THIS problem.

## Recommended Action

**Combine A + D:**
1. **Now (P1):** Implement Option A (split fetch into two timed jobs).
2. **Now (P1):** Pre-create FMP free-tier account as cold backup;
   document credentials handoff procedure.
3. **If A still flakes within 2 weeks of deploy (P2):** swap to FMP
   per Option D.

## Technical Details

**Affected files:**
- `scripts/fetch_prices.py` — add `--slice N/K` flag for alphabetical
  partitioning
- `.github/workflows/refresh-data.yml` — split into 2 jobs OR 2 cron
  entries
- Plan: update Phase 1 description, Phase 3 workflow yml, Risk
  Analysis (downgrade yfinance risk from "Medium likelihood" to
  "Confirmed daily; mitigated by split fetch")

## Acceptance Criteria

- [ ] Full-universe fetch achieves ≥95% ticker coverage in production
- [ ] Workflow completes both halves within combined 30-min budget
- [ ] Failed-ticker log is logged but never fails the workflow
- [ ] Plan reflects the mitigation in the workflow yml AND the risk
      table
- [ ] FMP free-tier account exists and credentials are documented
      for emergency swap

## Work Log

**2026-05-25:** Discovered during Phase 1 full-universe validation. 79%
failure rate on 6,509-ticker run. Screen output still usable (126 names)
but Phase 3 deploy blocked until mitigation lands.

## Resources

- yfinance #2422: https://github.com/ranaroussi/yfinance/issues/2422
- yfinance #2614: https://github.com/ranaroussi/yfinance/issues/2614
- FMP free tier: https://site.financialmodelingprep.com/developer/docs/pricing
- Plan reference: Phase 1, Phase 3 workflow yml, Risk Analysis table
