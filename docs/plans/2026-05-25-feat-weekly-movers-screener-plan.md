---
title: Weekly Movers — US Equity Screener with Per-Stock Dashboards
type: feat
status: active
date: 2026-05-25
date_deepened: 2026-05-25
origin: docs/brainstorms/2026-05-25-stock-screener-brainstorm.md
---

# Weekly Movers — US Equity Screener with Per-Stock Dashboards

## Enhancement Summary

**Deepened on:** 2026-05-25
**Sections enhanced:** 5 phases + 4 new appendices
**Agents consulted (parallel):** architecture-strategist, performance-oracle,
code-simplicity-reviewer, security-sentinel, data-integrity-guardian,
deployment-verification-agent, best-practices-researcher,
framework-docs-researcher, frontend-design (via general-purpose).

### Key Improvements (applied inline below)

1. **Single `period='1y'` yfinance pass** replaces the original two-pass
   (15d + 1y) strategy. Performance review showed two passes blow past the
   15-min GH Actions budget at p95; one pass + pandas slicing is faster
   and removes the screened-tickers-sequencing dependency.
2. **80-ticker chunks + 2s sleep + `curl_cffi` session** for yfinance.
   Community 2025–2026 consensus after Yahoo tightened rate limiting
   (yfinance issues #2422, #2614, #2633). 200-ticker chunks no longer
   reliable.
3. **Cron shifted to `30 11 * * 1-5`** (was `0 12 * * 1-5`). GitHub
   community data shows top-of-hour schedules have 15–30 min p50 drift;
   off-the-hour (e.g., `:17`, `:30`, `:43`) drops sharply.
4. **Bundled `docs/data/all.json.gz`** replaces 300 separate per-ticker
   JSON files. Saves ~90% of daily commit size and ~200–400ms detail-page
   LCP.
5. **Inline table data** as `<script type="application/json">` block
   eliminates the AJAX round-trip on the index page. Tabulator boots
   from inline data, zero network requests.
6. **XSS hardening on LLM-generated narratives:** `bleach` allowlist
   sanitization + Jinja2 `autoescape=select_autoescape` + CSP meta tag
   on `notes/<DATE>.html`. Plus prompt-injection defense (strip
   non-ASCII, cap ticker-name lengths before prompting Claude).
7. **Pipeline 2 freshness gate** — narrative script reads `last_session_date`
   from the run CSV and aborts if it doesn't match today's ET trading day.
   Prevents Pipeline 2 producing a "today" narrative if Pipeline 1 hasn't
   landed yet.
8. **5-day soak gate before Phase 4 deploys.** Phase 4 (Claude narrative)
   only begins after 5 consecutive green scheduled Pipeline 1 runs. The
   original "one workflow_dispatch is good" gate was too weak.
9. **Both push steps use pull-rebase-retry loop** to handle the
   two-writer git race between Pipeline 1 and Pipeline 2.
10. **Two distinct bot identities** (`data-bot@…`, `narrative-bot@…`)
    with commit-subject prefixes (`[data] …`, `[narrative] …`) for a
    clean `git log` audit trail.
11. **Lockfile + pinned `yfinance==<exact>` + SRI on committed JS assets**
    + GitHub secret scanning enabled. Supply-chain hardening.
12. **PAT expiry monitor workflow** — opens an issue at T-14 days when
    the fine-grained PAT is approaching expiry.
13. **Atomic file writes** (`tmp + os.replace`) for parquet, run CSV,
    and rendered HTML. Plus parquet content-hash recorded in run CSV
    header so `generate_site.py` can refuse to render if cache/run
    diverge.
14. **Frontend design system** added: Fraunces serif for display,
    JetBrains Mono with `tnum` for numbers, dark-mode default with
    semantic up/down/trigger color tokens, 1px sparkline strip behind
    ticker cells.
15. **Operational Playbook** appended — pre-deploy Go/No-Go checklist,
    first-run validation queries, rollback procedure, day-7 failure
    signals, week-1 morning ops checklist.

### New Considerations Discovered

- yfinance reliability has degraded meaningfully in 2025–2026. Pre-create
  a Financial Modeling Prep free-tier account as cold backup before
  Phase 1 starts.
- The single-bundle `all.json.gz` design assumes ≤500 screened tickers;
  past that, switch back to per-ticker files with delta-encoded Float32.
- `<meta name="robots" content="noindex">` worth considering on every
  page to avoid this being mistaken for financial advisory content by
  search engines (community convention for personal finance dashboards
  per 2025 disclaimer guidance).
- No first-class "shade a date range" primitive in Lightweight Charts
  v5 — use per-bar coloring for the last-5-session highlight.

### Tension Acknowledged

The simplicity reviewer correctly notes much of this plan is portfolio
ceremony for a one-user product (Pipeline 2, Jinja2, Tabulator, KaTeX,
mobile QA, custom domain, etc.). That review's aggressive-cut list is
captured verbatim in the **Aggressive YAGNI Fallback** appendix as an
escape hatch if Phase 1 pace slips — not as the primary path, because
Shehral has explicitly chosen the full feature set and intends this as
a public artifact.

## Overview

A public GitHub Pages site (`shehral.github.io/weekly-movers` or a custom
domain) that screens US-listed equities every trading-day morning before
market open. Two volatility buckets:

- **Bucket A — Mid-priced movers:** $300–$800, weekly absolute variation ≥ $15
- **Bucket B — Penny movers:** $0.79–$20, weekly relative variation ≥ 20%

Each screened ticker gets a per-stock dashboard with a toggleable
candlestick chart (1M / 6M / 1Y) and the three variation metrics. A
Claude-generated daily note summarizes what's notable in today's list and
what changed versus yesterday.

Two pipelines:

1. **GitHub Actions cron** (11:30 UTC, Mon–Fri) — deterministic data refresh,
   site generation, commit & push.
2. **Claude agents cloud routine** (~12:30 UTC, Mon–Fri) — narrative
   generation, commits a daily note to `docs/notes/`.

See origin brainstorm: [`docs/brainstorms/2026-05-25-stock-screener-brainstorm.md`](../brainstorms/2026-05-25-stock-screener-brainstorm.md).
Key decisions carried forward: (1) three variation definitions shown
side-by-side with OR-combining for inclusion, (2) `$1M` average dollar
volume floor on both buckets, (3) trailing 5 trading days rolling window,
(4) yfinance + NASDAQ-listed universe only, (5) TradingView Lightweight
Charts v5 for charts, (6) split-pipeline architecture (GH Actions + Claude
routine).

## Problem Statement

Most public screeners either lock the math behind a sign-up (Finviz Elite,
TradingView paid tiers) or expose only a single rigid definition of
volatility. For a personal research workflow that targets two specific
trade types — mid-priced range-traders and high-volatility penny names —
we want:

- A reproducible, transparent screen (math is published on the site)
- Three complementary variation definitions because "weekly move" is
  not one thing
- Daily refresh before market open, no manual work
- Per-stock context so a name in the list is immediately scannable
- A free, public artifact that doubles as a portfolio piece

No off-the-shelf tool combines those.

## Proposed Solution

A static Python-rendered site, refreshed via two scheduled pipelines that
write commits back to the repo. GitHub Pages serves the result.

The deterministic data pipeline owns: universe selection, price
download, screen computation, HTML rendering. The LLM-driven narrative
pipeline owns only the daily commentary — it reads the latest run CSV plus
yesterday's, and writes one markdown file.

## Technical Approach

### Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Standard for yfinance + pandas |
| Data source | yfinance (latest) | Free, no API key, covers NYSE+NASDAQ listed |
| Universe source | NASDAQ Trader symbol directory | Canonical, free, two text files |
| Trading-day check | `pandas_market_calendars` | NYSE calendar baked in |
| OHLC cache format | Parquet (via `pyarrow`) | Columnar, compressed, safe deserialization (vs pickle) |
| Templating | Jinja2 | Stable, ubiquitous |
| Table UI | Tabulator.js (CDN) | Sortable / searchable / mobile-responsive, no build |
| Chart library | TradingView Lightweight Charts v5.2 (CDN) | Candlesticks + volume, ~45KB, MIT |
| Site host | GitHub Pages (from `docs/` on `main`) | Free, custom-domain capable |
| Data cron | GitHub Actions, `30 11 * * 1-5` UTC | Free for public repos, native cron; off-the-hour avoids drift |
| Narrative cron | Claude agents cloud routine via `/schedule` | Where LLM judgment adds value |
| Narrative LLM | Claude Sonnet 4.6 by default | Cheap (<$5/yr) and good enough |

### Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  Pipeline 1 — Data refresh                                     │
│  GitHub Actions cron: 30 11 * * 1-5  (11:30 UTC)              │
│                                                                │
│  fetch_universe.py    weekly (Mondays)  → data/universe.csv    │
│  fetch_prices.py      every run         → data/cache/<DATE>.parquet │
│  compute_screens.py   every run         → data/runs/<DATE>.csv │
│  generate_site.py     every run         → docs/{index,stocks/*, │
│                                                  data/*}.html  │
│  git commit + push                                             │
│                                                                │
│  ↓ GitHub Pages serves docs/                                   │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  Pipeline 2 — Narrative                                        │
│  Claude routine cron: ~12:30 UTC, Mon–Fri (after Pipeline 1)  │
│                                                                │
│  clone repo                                                    │
│  generate_narrative.py  reads data/runs/<today>.csv +          │
│                         data/runs/<yesterday>.csv              │
│                         calls Claude → docs/notes/<DATE>.html  │
│  git commit + push                                             │
└────────────────────────────────────────────────────────────────┘
```

### Three Variation Formulas (Trailing 5 Trading Days)

| Name | Bucket A (price $300–$800) | Bucket B (price $0.79–$20) | Catches |
|---|---|---|---|
| **Range** | `max(High) − min(Low) ≥ $15` | `max(High)/min(Low) − 1 ≥ 0.20` | Choppy / two-sided volatility |
| **5-day return** | `\|Close[t] − Close[t−5]\| ≥ $15` | `\|Close[t]/Close[t−5] − 1\| ≥ 0.20` | Directional trend |
| **Max daily move** | `max_{i∈last 5}\|Δclose_i\| ≥ $15` | `max_{i∈last 5}\|pct Δclose_i\| ≥ 0.20` | Event-driven spike |

A ticker is included in its bucket if **any one** of the three is true.
Each row shows all three numerical values plus three triggered/untriggered
badges. The site footer renders these formulas as LaTeX.

Universe filters applied first (cheap):
- `last_close` in band (Bucket A: 300–800; Bucket B: 0.79–20)
- 30-day average dollar volume ≥ $1,000,000
- Common stock only (no ETFs, ADRs, warrants, rights, units)

### Repository Structure

```
weekly-movers/
├── .github/workflows/
│   └── refresh-data.yml             # Pipeline 1 cron
├── scripts/
│   ├── fetch_universe.py
│   ├── fetch_prices.py
│   ├── compute_screens.py
│   ├── generate_site.py
│   ├── generate_narrative.py        # called by Pipeline 2
│   └── _common.py                   # paths, ET clock, constants
├── templates/
│   ├── base.html.j2
│   ├── index.html.j2
│   ├── stock.html.j2
│   └── notes.html.j2
├── data/
│   ├── universe.csv                 # weekly refresh (committed)
│   ├── cache/<DATE>.parquet         # gitignored; OHLC bulk cache
│   └── runs/<DATE>.csv              # committed screen results
├── docs/                            # GH Pages root
│   ├── index.html
│   ├── about.html                   # math explanation + disclaimer
│   ├── stocks/<TICKER>.html
│   ├── notes/<DATE>.html
│   ├── data/all.json.gz            # bundled OHLC for all screened tickers
│   └── assets/
│       ├── lightweight-charts.standalone.production.js  # v5.2.0
│       ├── tabulator.min.js
│       ├── tabulator.min.css
│       └── style.css
├── requirements.txt
├── .gitignore                       # data/cache/, .venv/
└── README.md
```

### Implementation Phases

#### Phase 1 — Local data pipeline (1 work session)

**Goal:** End-to-end data flow on a 50-ticker test universe, screen logic
validated.

Files to create:
- `requirements.txt`
  ```
  yfinance>=0.2.50
  pandas>=2.2
  pyarrow>=15.0           # for parquet cache
  pandas_market_calendars>=4.4
  jinja2>=3.1
  requests>=2.32
  markdown-it-py>=3.0
  anthropic>=0.42         # used by Pipeline 2
  ```
- `scripts/_common.py` — `ROOT`, `DATA`, `DOCS`, `today_et()`, constants
- `scripts/fetch_universe.py` — pulls `nasdaqlisted.txt` and
  `otherlisted.txt` from `https://www.nasdaqtrader.com/dynamic/symdir/`,
  filters out ETFs, test issues, non-normal financial-status rows, and
  symbols with special characters (`=`, `.`, `$`). Writes
  `data/universe.csv` with columns `symbol, name, exchange`.
- `scripts/fetch_prices.py` — reads universe, calls `yf.download(...)`
  in **80-ticker chunks with a 2-second sleep between chunks** and
  `period='1y', interval='1d', group_by='ticker', threads=True,
  auto_adjust=True`. Sets `yf.config.network.retries = 3`. **Passes a
  shared `curl_cffi.requests.Session(impersonate="chrome")`** session
  for browser TLS fingerprinting (community 2025-2026 consensus per
  yfinance issues #2422, #2614). Pivots the resulting DataFrame into
  a long-format frame (`ticker, date, open, high, low, close, volume`)
  and writes `data/cache/<DATE>.parquet` via `tmp + os.replace`
  (atomic). Logs tickers with empty/short results.

  **Single `period='1y'` pass** (not the original two-pass 15d + 1y
  plan) serves both the screen computation (slice trailing 5 sessions
  in pandas) and chart data (slice last 252 sessions). Bandwidth cost
  is dominated by request setup, not payload size.

  Long-format parquet rationale: easier to filter and resume from than
  yfinance's native wide multi-index columns; small (~10MB compressed
  for 8000 tickers × 252 days); plays well with `pd.read_parquet(...,
  filters=[('ticker', '==', 'NVDA')])`.

  Parquet content hash (SHA256 of bytes) is written into the run CSV
  header by `compute_screens.py` so `generate_site.py` can refuse to
  render if cache and run CSV diverge (same-day rerun safety).

- `scripts/compute_screens.py` — loads the parquet, applies price-band +
  volume filters, computes the three variation metrics, writes
  `data/runs/<DATE>.csv` with columns:
  `ticker, bucket, name, sector, last_close, avg_dollar_vol,
   range_value, range_triggers, ret_5d_value, ret_5d_triggers,
   max_daily_value, max_daily_triggers, last_session_date`.

**Verification (acceptance):**
- Run `python scripts/compute_screens.py` against a curated 50-ticker
  universe; expect Bucket A to surface NVDA/META-class names on
  high-vol weeks; Bucket B to surface biotech/momentum penny names.
- Manually inspect 3 names per bucket; their variation values should
  match a Yahoo Finance chart inspection.
- Edge cases tested: ticker with <5 days of history (skip), ticker with
  recent split (no fake variation), all-three triggers fire, only-one
  trigger fires.

**Open implementation question (for ce:work):**
- Bucket-A 5-day return formula uses dollar change `|Close[t] −
  Close[t−5]|`, but if a stock split between t−5 and t, the
  adjusted-price subtraction still works correctly. Add a comment
  flagging this.

#### Phase 1 — Research Insights

**Best practices (yfinance large-universe downloads, 2025–2026):**
- Rate limiting tightened materially in early 2025 (yfinance issues
  #2422, #2614, #2633). `YFRateLimitError('Too Many Requests')` now
  fires on basic `Ticker.info` calls without backoff.
- Chunk size 80 (not the original 200); 2s sleep between chunks
  minimum. Some practitioners use 5–10s for resilience.
- `curl_cffi.requests.Session(impersonate="chrome")` passed to
  `yf.Ticker()` or `yf.download(session=...)` defeats TLS
  fingerprinting and is now near-mandatory for high-volume jobs.
- Pre-create a **Financial Modeling Prep free-tier** account as cold
  fallback before Phase 1 starts. If yfinance breaks mid-quarter,
  you'll want the alternative provider ready, not researched in panic.
- Expected partial failures for 5000+ tickers — log failed tickers,
  continue with the rest. Don't fail the workflow on individual ticker
  errors.

**Implementation snippet:**
```python
import yfinance as yf
import curl_cffi.requests as cc
import time

session = cc.Session(impersonate="chrome")
yf.config.network.retries = 3

tickers = universe['symbol'].tolist()
chunks = [tickers[i:i+80] for i in range(0, len(tickers), 80)]
frames = []
failed = []
for i, chunk in enumerate(chunks):
    try:
        df = yf.download(chunk, period='1y', interval='1d',
                         group_by='ticker', threads=True,
                         auto_adjust=True, session=session, progress=False)
        frames.append(pivot_to_long(df))
    except Exception as e:
        failed.extend(chunk)
        log.warning(f"Chunk {i} failed: {e}")
    if i < len(chunks) - 1:
        time.sleep(2.0)
```

**References:**
- yfinance #2422 — rate limit: https://github.com/ranaroussi/yfinance/issues/2422
- yfinance #2633 — curl_cffi SSL: https://github.com/ranaroussi/yfinance/issues/2633
- QuantVPS yfinance migration guide: https://www.quantvps.com/blog/yahoo-finance-api-documentation

#### Phase 2 — Site generation (1 work session)

**Goal:** Full local site: index + per-ticker pages with working charts.

Files to create:
- `templates/base.html.j2` — shared layout, head, footer with formula
  block and disclaimer, "as of" timestamp.
- `templates/index.html.j2` — two `<section>` blocks (Bucket A, Bucket
  B), each rendering a `<table class="screener-table">` consumed by
  Tabulator.js. Columns: ticker (link), name, sector, last close, three
  variation values with trigger badges, avg dollar volume.
- `templates/stock.html.j2` — header (ticker, name, day Δ), three
  variation cards, candlestick chart container with timeframe buttons,
  stats block, outbound links (Yahoo, SEC EDGAR, Google News).
- `scripts/generate_site.py`:
  - Loads `data/runs/<DATE>.csv` + the parquet OHLC cache (single 1y
    fetch from Phase 1 covers both screen logic and chart history).
  - Renders `docs/index.html` with **inline table data** as a
    `<script type="application/json" id="screen-data">` block; Tabulator
    boots from inline data, no AJAX. Saves 150–250ms FCP.
  - For each screened ticker: renders `docs/stocks/<TICKER>.html`
    (skeleton, no embedded data).
  - Writes a single **bundled `docs/data/all.json.gz`** indexed by
    ticker. Detail pages lazy-load it via one HTTP/2 transfer
    (~400KB). Replaces 300 separate per-ticker JSON files (saves
    ~90% of daily commit size, ~200–400ms detail-page LCP).
  - Renders `docs/about.html` (static-ish — math + disclaimer).
  - Copies static assets from local `assets/` to `docs/assets/` on
    first run; subsequent runs assume committed.
  - **Staleness guard:** before regenerating `docs/stocks/` and
    `docs/data/`, deletes files NOT in today's screened set (set-diff,
    not blanket `rm -rf`). Uses Path-based deletion with
    `assert target.resolve().is_relative_to(DOCS.resolve())` to prevent
    misconfigured-CWD accidents.
  - Writes every output file via `tmp + os.replace` (atomic).
- `docs/assets/style.css` — typography, dark mode default, mobile
  layout, trigger badge color coding.
- `docs/assets/screener.js` — boots Tabulator on both tables.
- `docs/assets/stock-chart.js` — boots Lightweight Charts:

  ```javascript
  import { createChart, CandlestickSeries, HistogramSeries, PriceScaleMode }
    from './lightweight-charts.standalone.production.js';

  const chart = createChart(document.getElementById('chart'), { ... });
  const candles = chart.addSeries(CandlestickSeries, { ... });
  const volume  = chart.addSeries(HistogramSeries,
    { priceFormat: { type: 'volume' }, priceScaleId: '' });
  volume.priceScale().applyOptions({
    scaleMargins: { top: 0.75, bottom: 0 }
  });

  // Bucket B → log axis
  if (window.__BUCKET__ === 'B') {
    chart.priceScale('right').applyOptions({
      mode: PriceScaleMode.Logarithmic,
    });
  }

  // Timeframe buttons filter the in-memory series client-side
  document.querySelectorAll('.tf-btn').forEach(b => b.onclick = () => {
    const days = parseInt(b.dataset.days);
    candles.setData(full.slice(-days));
    volume.setData(vol.slice(-days));
    chart.timeScale().fitContent();
  });
  ```

  Notes:
  - Lightweight Charts v5 uses `addSeries(SeriesType, opts)` — not the
    v4 `addCandlestickSeries(opts)` form. Verified against the v5.2 docs.
  - The full 1Y of candles is delivered via the bundled
    `docs/data/all.json.gz` indexed by ticker; the 1M/6M views are
    client-side slices. No re-fetch on toggle.
  - `createChart(container, { autoSize: true })` wires its own
    ResizeObserver — drop manual `window.addEventListener('resize')`.
  - **Last-5-session highlight uses per-bar coloring**, not range
    shading. v5 has no first-class "shade a date range" primitive; the
    idiomatic path is to set `color`, `wickColor`, `borderColor` per
    candle data point for the last 5 entries (e.g., amber tint).
  - Bucket B → `PriceScaleMode.Logarithmic` on right scale by default,
    Bucket A → `Normal`. Toggle button persists choice in
    `localStorage`.
  - Lazy-load the chart bundle via `<script type="module" defer>` so it
    doesn't block FCP on the detail page.

**Verification:**
- Open `docs/index.html` in a browser.
- Both tables render, are sortable on every column, searchable on
  ticker/name.
- Click a ticker → detail page; candlestick + volume chart loads in
  <500ms; timeframe buttons switch ranges without flicker; Bucket B
  chart is on log scale.
- Resize browser to mobile width; tables collapse to readable form.
- Disclaimer ("not financial advice") visible in footer.

#### Phase 2 — Research Insights

**Frontend design tokens (full set in appendix; key choices here):**
- "Indie-research terminal with FT polish" — not Bloomberg, not Robinhood.
- Display serif: **Fraunces** (variable, opt 144, soft) at h1/h2 and on
  notes pages only. Body UI: **Geist** (not Inter — too overused).
  Numerics everywhere: **JetBrains Mono** with
  `font-feature-settings: 'tnum' 1, 'zero' 1` so prices/percentages
  align tabularly without `text-align: right` hacks.
- Dark-mode default (`--bg-0: #0B0D10`, `--text-hi: #E8EAED`); semantic
  `--up: #4ADE80`, `--down: #F87171`, `--trigger: #F5C451`,
  `--accent: #7DD3FC`. Triggered badges are filled chips, untriggered
  are dimmed outlined chips (don't hide untriggered — readers want to
  see what didn't fire).
- **Memorable detail (the screenshot moment):** 1px-tall sparkline
  strip behind each table row's ticker cell — 5-day close in
  `--accent` at 30% opacity, no axes. Costs no row height; tells the
  *shape* of the move before the reader processes the numbers.

**Tabulator v6 idioms:**
- `responsiveLayout: 'collapse'` (not `'hide'`) — mobile rows collapse
  into expandable 2-line micro-cards: line 1 = `TICKER  $price  ±change%`,
  line 2 = mono pills for triggered variations only.
- Sort by computed `score` column via `mutator` that runs at load.
- Row click → `window.location.href = /stocks/<TICKER>.html` with
  `metaKey/ctrlKey` opening new tab.
- Set `responsive: 0` on Ticker + Score columns so they never hide.

**Lightweight Charts v5 — concrete idioms:**
```javascript
import {
  createChart, CandlestickSeries, HistogramSeries, PriceScaleMode,
} from './lightweight-charts.standalone.production.js';

const chart = createChart(container, { autoSize: true, ... });
const candles = chart.addSeries(CandlestickSeries, { ... });
const volume  = chart.addSeries(HistogramSeries,
  { priceFormat: { type: 'volume' }, priceScaleId: '' });
volume.priceScale().applyOptions({ scaleMargins: { top: 0.7, bottom: 0 } });
candles.priceScale().applyOptions({ scaleMargins: { top: 0.1, bottom: 0.3 } });

// Last-5-session highlight via per-bar coloring
const last5 = new Set(ohlc.slice(-5).map(b => b.time));
candles.setData(ohlc.map(b => last5.has(b.time)
  ? { ...b, color: '#F5C45140', wickColor: '#F5C45180', borderColor: '#F5C451' }
  : b));
```

**Performance considerations:**
- Inline table data via `<script type="application/json">` — eliminates
  AJAX round-trip on index page (saves 150–250ms FCP, hits the <1s 4G
  target reliably).
- Bundled `all.json.gz` — single HTTP/2 transfer vs 300 requests; ~90%
  smaller commit; ~200–400ms detail-page LCP improvement.
- `chart.timeScale().fitContent()` once after `setData`, not on every
  interaction.
- For very-mobile experience, disable hover crosshair: `chart.applyOptions({ trackingMode: { exitMode: 0 } })`.

**Edge cases:**
- v5 named exports only work with module imports; UMD build exposes
  them on `LightweightCharts.*`. Pin the module form.
- Tabulator `mutator` re-runs on data updates; for one-shot computation
  use `tableBuilt` callback or pre-compute server-side.

**References:**
- Lightweight Charts v5.2: https://tradingview.github.io/lightweight-charts/
- Tabulator v6.4: https://tabulator.info/docs/6.4

#### Phase 3 — GitHub Actions + Pages deploy (1 work session)

**Goal:** Cron-driven daily refresh live at the public URL.

Files to create:
- `.github/workflows/refresh-data.yml`:

  ```yaml
  name: Refresh screener data
  on:
    schedule:
      - cron: '30 11 * * 1-5'      # 11:30 UTC ≈ 6:30am EDT / 7:30am EST
                                    # Off-the-hour avoids top-of-hour drift
                                    # (GH community data: :00 schedules drift
                                    # 15-30 min p50; off-hour drops sharply)
    workflow_dispatch:

  permissions:
    contents: write
    actions: read

  concurrency:
    group: writeback                # Shared lock with narrative routine
    cancel-in-progress: false

  jobs:
    refresh:
      runs-on: ubuntu-latest
      timeout-minutes: 30
      steps:
        - uses: actions/checkout@v4
          with:
            fetch-depth: 1
        - uses: actions/setup-python@v5
          with:
            python-version: '3.12'
            cache: 'pip'
        - run: pip install --require-hashes -r requirements.lock
        - name: Refresh universe (Mondays + workflow_dispatch only)
          run: |
            if [[ $(date -u +%u) == 1 || "${{ github.event_name }}" == "workflow_dispatch" ]]; then
              python scripts/fetch_universe.py
            fi
        - run: python scripts/fetch_prices.py
        - run: python scripts/compute_screens.py
        - run: python scripts/generate_site.py
        - name: Commit & push (with rebase retry)
          run: |
            git config user.name  "weekly-movers-data-bot"
            git config user.email "data-bot@users.noreply.github.com"
            git add docs/ data/universe.csv data/runs/
            if git diff --staged --quiet; then
              echo "No changes"
              exit 0
            fi
            git commit -m "[data] Refresh $(date -u +%Y-%m-%d) [skip ci]"
            for i in 1 2 3 4 5; do
              git pull --rebase --autostash origin main && git push && exit 0
              sleep $((RANDOM % 10 + 5))
            done
            echo "::error::Push failed after 5 retries"
            exit 1
  ```

- `.gitignore`:
  ```
  data/cache/
  .venv/
  __pycache__/
  *.pyc
  .DS_Store
  ```

- `README.md` — sections: what this is, how to read it, how the math
  works, disclaimer, link to live site.

Repo setup steps (manual, documented in README):
1. Create public repo `shehral/weekly-movers` on GitHub.
2. `git remote add origin git@github.com:shehral/weekly-movers.git`,
   push.
3. Settings → Pages → Source: `Deploy from a branch`, Branch: `main`,
   Folder: `/docs`.
4. Settings → Actions → General → Workflow permissions: "Read and
   write permissions" (so `GITHUB_TOKEN` can push commits).
5. Trigger first run via `workflow_dispatch` to validate.

**Verification:**
- `workflow_dispatch` succeeds end-to-end on GH Actions; total run
  time <15 min.
- Commit lands on `main` with `docs/index.html`, `docs/stocks/*.html`,
  `data/runs/<DATE>.csv` updated.
- Site loads at `https://shehral.github.io/weekly-movers/`.
- Next scheduled run fires on the next weekday (or fires today if
  scheduled time hasn't passed).
- **Phase 4 gate:** before starting Phase 4 work, observe **5
  consecutive green scheduled runs** of Pipeline 1 (not counting
  `workflow_dispatch`). The architecture-strategist review notes that
  one manual success is too weak to "prove" the pipeline.

#### Phase 3 — Research Insights

**Best practices (CI commits pushed back, 2025–2026 consensus):**
- Use a **dedicated bot identity per pipeline** for a clean audit
  trail. Pipeline 1 → `data-bot@users.noreply.github.com`; Pipeline 2
  → `narrative-bot@users.noreply.github.com`. Prefix commit subjects:
  `[data] …` and `[narrative] …`.
- **`[skip ci]` in commit subject** prevents CI loops. Note: commits
  made via the default `GITHUB_TOKEN` don't trigger downstream
  workflows anyway, but `[skip ci]` is belt-and-suspenders.
- **Pull-rebase-retry loop** before push handles the two-writer race
  between Pipeline 1 and Pipeline 2. Use `--rebase --autostash`,
  retry 5× with jittered sleep. Do NOT use `--force` or
  `--force-with-lease` for the daily cron — let the loop converge.
- **Shared `concurrency: group: writeback`** across both pipelines
  serializes their pushes within GH Actions; combined with the
  rebase-retry it handles all collision modes.
- Enable **GitHub secret scanning + push protection** on the repo so
  an accidental PAT commit is blocked at push time.
- Use **lockfile with hashes** (`pip-compile --generate-hashes`) and
  `pip install --require-hashes` for supply-chain integrity.
- Add **SRI attributes** on any CDN-loaded JS (`integrity="sha384-…"
  crossorigin="anonymous"`); prefer committing the assets locally to
  avoid CDN trust altogether.

**Cron drift mitigation:**
- GitHub community has reported 15–30 min p50 drift for `0 * * * *`
  schedules (Discussion #146923, April 2025 Discussion #156282).
  Worst-case observed: 60+ min, occasional missed runs entirely.
- Off-the-hour minutes (e.g., `:17`, `:30`, `:43`) drop drift sharply.
  Plan uses `30 11 * * 1-5` for this reason.
- 11:30 UTC = 6:30am EDT / 7:30am EST. Even with 90-min drift, still
  pre-market (9:30am ET open).

**Edge cases:**
- `actions/checkout@v4` with `fetch-depth: 1` is fine for read; rebase
  loop fetches more as needed.
- `permissions: actions: read` explicitly granted so the workflow
  could (in a future iteration) inspect prior runs without elevation.
- `pull-requests: none`, `packages: none`, etc. all default-deny once
  `permissions:` is set explicitly — good. Don't expand.

**References:**
- stefanzweifel/git-auto-commit-action:
  https://github.com/stefanzweifel/git-auto-commit-action
- GH Discussion #146923 — top-of-hour drift:
  https://github.com/orgs/community/discussions/146923
- GH Discussion #156282 — April 2025 cron delays:
  https://github.com/orgs/community/discussions/156282
- 2025 GH Actions best practices (Suzuki):
  https://suzuki-shunsuke.github.io/slides/github-actions-best-practice-2025
- crontap drift analysis:
  https://crontap.com/blog/github-actions-cron-drift-problem

#### Phase 4 — Claude narrative routine (1 work session)

**Goal:** Daily commentary commits to the repo.

Files to create:
- `scripts/generate_narrative.py`:
  - **Freshness gate:** reads `data/runs/<today>.csv` and asserts
    `last_session_date == today_et_trading_day()`. Aborts loudly if
    not — prevents Pipeline 2 producing a "today" narrative when
    Pipeline 1 hasn't landed.
  - **Idempotency check:** if `docs/notes/<DATE>.html` already exists
    and `--force` not passed, skip (don't silently overwrite the
    narrative with a non-deterministic LLM resample).
  - Loads `data/runs/<today>.csv` and the most recent prior trading
    day's CSV.
  - Computes three sets: `new_today` (in today not yesterday),
    `dropped_today` (in yesterday not today), `persistent` (in both).
  - Builds a structured prompt for Claude including: today's top
    movers by each of the 3 metrics per bucket, the three diff sets,
    sector breakdown. **Prompt-injection defense:** strip non-ASCII
    from ticker names + cap each field to 64 chars before prompting.
  - Calls Anthropic API (`claude-sonnet-4-6`) for a ~200-word note
    in two parts: "Notable today" + "What changed vs yesterday".
  - **XSS sanitization on LLM output:** parse Claude's markdown via
    `markdown-it-py`, then `bleach.clean()` with a strict allowlist
    (`p, strong, em, ul, ol, li, code, a, br`; only `href` on `a`;
    only `https` protocol; `strip=True`). Renders the sanitized HTML
    inside Jinja2 with `autoescape=select_autoescape(['html','j2'])`
    enabled at the Environment level.
  - Renders to `docs/notes/<DATE>.html` via `templates/notes.html.j2`.
    The template includes a CSP meta tag:
    `<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'self'">`.
  - Writes the output file via `tmp + os.replace` (atomic).
- `templates/notes.html.j2` — same `base` template, just renders the
  narrative HTML block. Uses `{{ narrative | safe }}` only after
  bleaching above.
- `.github/workflows/pat-expiry-check.yml` — weekly workflow that
  calls `GET /user` with the PAT, parses `X-GitHub-Token-Expiration`,
  opens a GitHub issue at T-14 days. Prevents silent push failures
  after PAT lapse.

Routine setup (manual, documented in README):
1. Create fine-grained PAT at github.com/settings/tokens, scoped to
   `shehral/weekly-movers` only, `contents: write` only, 90-day expiry.
2. Add `/schedule` Claude routine:
   - Cron: `30 12 * * 1-5` UTC (1 hour after data refresh start;
     freshness gate handles the rest)
   - Env: `GH_TOKEN=<fine-grained-PAT>`,
          `ANTHROPIC_API_KEY=<key>`
   - Script body: clone repo with `GH_TOKEN` (via
     `https://x-access-token:$GH_TOKEN@github.com/...`, never echoed),
     install requirements with `--require-hashes`, run
     `python scripts/generate_narrative.py`, commit as
     `narrative-bot` with `[narrative]` prefix, push with the same
     pull-rebase-retry loop as Pipeline 1.
   - **Fail-closed:** routine exits non-zero if `GH_TOKEN` or
     `ANTHROPIC_API_KEY` env vars are unset — never silently degrade
     to anonymous mode.

**Verification:**
- Manually run the routine via `/schedule run weekly-movers-narrative`.
- A note appears at `docs/notes/<DATE>.html` linked from the index.
- Diff section correctly identifies tickers that left/joined.
- API cost confirmed via Anthropic console <$0.02/day.
- **Attempted-injection test:** manually inject a `<script>` in a
  ticker name in `data/runs/<DATE>.csv`, rerun narrative, verify it
  doesn't appear as executable JS in the rendered note (bleach
  stripped it).
- PAT expiry workflow opens an issue when PAT is set to expire
  within 14 days.

#### Phase 4 — Research Insights

**Security hardening (LLM-generated HTML is the highest-risk vector):**
- LLM outputs to be rendered as HTML are **untrusted input by default**.
  Either render as escaped text or run through an allowlist sanitizer.
  Plan uses `bleach` with a deliberately minimal tag/attribute set.
- Jinja2 `autoescape` must be enabled at the Environment level — easy
  to forget if you start from a script that doesn't set it.
- CSP meta tags on GH Pages: `<meta http-equiv="Content-Security-Policy">`
  works (no native HTTP-header support on GH Pages free tier), so
  putting CSP in the document is the only practical option.
- **Prompt-injection from ticker names:** Yahoo can return weird
  Unicode in security names (M&A merger names, foreign issuers, etc.)
  that could include adversarial-looking text. Cap field lengths and
  strip non-ASCII before constructing the prompt.

**State/integrity (two-writer race + idempotency):**
- The freshness gate (`last_session_date == today`) is the cheapest
  way to prevent Pipeline 2 from producing wrong narratives if
  Pipeline 1 is late. Pure data-driven check, no time-of-day coupling.
- Idempotency: same-day reruns must not overwrite narrative HTML by
  default. If you need to regenerate, pass `--force` explicitly and
  bump filename to `<DATE>-v2.html`.
- Both pipelines use the same `concurrency: group: writeback` lock
  AND the rebase-retry loop. Lock alone is insufficient because
  Pipeline 2 runs from Claude agents cloud, outside GH Actions'
  concurrency scope — the lock applies only between GH Actions
  workflows.

**Implementation snippet (bleach + Jinja2 setup):**
```python
import bleach
import markdown_it
from jinja2 import Environment, FileSystemLoader, select_autoescape

env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html", "j2"]),
)

ALLOWED_TAGS = ["p", "strong", "em", "ul", "ol", "li", "code", "a", "br"]
ALLOWED_ATTRS = {"a": ["href"]}

md_html = markdown_it.MarkdownIt().render(claude_text)
safe_html = bleach.clean(
    md_html,
    tags=ALLOWED_TAGS,
    attributes=ALLOWED_ATTRS,
    protocols=["https"],
    strip=True,
)
rendered = env.get_template("notes.html.j2").render(narrative=safe_html, date=today)
```

**References:**
- bleach docs: https://bleach.readthedocs.io/
- Jinja2 autoescape: https://jinja.palletsprojects.com/en/3.1.x/api/#autoescaping
- Anthropic prompt-injection guidance:
  https://docs.anthropic.com/claude/docs/security

#### Phase 5 — Polish (1 work session)

**Goal:** Production-quality public artifact.

- `docs/about.html` — full methodology page: each formula in LaTeX
  (rendered via KaTeX CDN), worked examples, known limitations
  (yfinance is unofficial, no after-hours data, etc.), disclaimer.
- Holiday banner: `compute_screens.py` detects NYSE-closed days via
  `pandas_market_calendars`; writes a flag into the run CSV;
  `index.html.j2` renders a banner "Markets closed today (US Federal
  holiday). Showing screen as of last session close (YYYY-MM-DD)."
- Custom domain (optional): CNAME `screener.shehral.com` →
  `shehral.github.io`. Add `docs/CNAME` file.
- README polish: screenshot of dashboard, badge for last successful
  refresh.
- Mobile QA on iPhone Safari and Android Chrome.
- Add `docs/notes/index.html` listing past narratives.

**Verification:**
- All five phase verifications still pass.
- About page renders LaTeX correctly.
- A simulated holiday (e.g., set system date to July 4) produces the
  banner.

## Alternative Approaches Considered

| Alternative | Why rejected |
|---|---|
| **Single GH Actions workflow that also calls Claude** | Mixes deterministic data refresh with LLM cost/latency variability; harder to reason about failures; pricier per failed/re-run |
| **Streamlit / FastAPI dynamic backend** | Hosting cost, complexity, no value over static — daily refresh doesn't need a server |
| **Polygon.io / Alpha Vantage paid data** | $29/mo+, unnecessary given the $0.79 floor stays out of true OTC pink sheets |
| **Plotly for charts** | ~3MB JS bundle, overkill, no native candlestick UX |
| **Pre-rendered PNG charts via matplotlib** | Loses interactivity (timeframe toggle, hover crosshair); slower per-ticker generation |
| **Pickle for OHLC cache** | Arbitrary code execution risk if ever loaded from untrusted source; Parquet is faster, smaller, columnar, inspectable |
| **Persist detail pages indefinitely** | More state, link rot still possible; v1 keeps it simple; `data/runs/` history allows v2 backfill if needed |
| **Calendar-week "Mon–Fri" window** | Wednesday refresh would compare to stale Friday close; trailing 5 sessions is the right granularity |
| **Require ALL 3 variation definitions to trigger** | Too restrictive; OR-combining with side-by-side display lets the reader filter visually |
| **Polars instead of pandas** | Marginal speedup on 8000-row math; pandas is the ecosystem default; not worth the dependency divergence from yfinance |

## System-Wide Impact

### Interaction Graph

Action: GH Actions cron fires at 11:30 UTC.

```
GitHub Actions runner
  └─ fetch_universe.py (Mondays)
       └─ HTTP GET to nasdaqtrader.com
            └─ writes data/universe.csv
  └─ fetch_prices.py
       └─ yfinance → Yahoo Finance API (8000 tickers, chunked)
            └─ writes data/cache/<DATE>.parquet (gitignored)
  └─ compute_screens.py
       └─ reads parquet + universe.csv
            └─ writes data/runs/<DATE>.csv
  └─ generate_site.py
       └─ reads run CSV + parquet
            └─ writes docs/index.html
            └─ writes docs/stocks/<TICKER>.html × N
            └─ writes docs/data/all.json.gz (bundled, indexed by ticker)
  └─ git commit + push
       └─ triggers GitHub Pages deploy
            └─ live at shehral.github.io/weekly-movers in ~60s
```

One hour later (~12:30 UTC): Claude routine clones, runs narrative
script (with freshness gate), pushes `docs/notes/<DATE>.html`, second
Pages deploy.

### Error & Failure Propagation

| Failure | Layer | Visible where | Recovery |
|---|---|---|---|
| yfinance returns empty for ticker | `fetch_prices.py` | log line, ticker absent from cache | filter in `compute_screens.py`, ticker simply not in screen |
| yfinance rate-limited (`YFRateLimitError`) | `fetch_prices.py` | `yf.config.network.retries=3` + exponential backoff | If still failing, log and continue with partial universe; alert via workflow annotation |
| NASDAQ Trader file 404 | `fetch_universe.py` | non-Mon: skipped; Mon: workflow fails | Re-run after delay; `data/universe.csv` is committed, so a stale universe is fine for days |
| No screened tickers today | `compute_screens.py` | empty `data/runs/<DATE>.csv` | `generate_site.py` renders "No tickers met criteria today" empty-state |
| GH Actions push conflict | workflow `Commit & push` step | step fails | `concurrency: refresh-data, cancel-in-progress: false` prevents overlap; rebase on next run |
| GH Pages deploy fails | GH Pages action | repo Actions tab | rare; usually retryable |
| Anthropic API timeout | Pipeline 2 | routine error | retry once; if still failing, skip note for today |
| PAT expired | Pipeline 2 push | `git push` fails | calendar reminder to rotate every 80 days |

### State Lifecycle Risks

- **`data/runs/` grows unbounded.** ~5KB/day × 252/yr ≈ 1.3MB/yr.
  Bounded by GH 1GB repo soft cap for ~750 years. No cleanup needed
  for foreseeable horizon.
- **`docs/stocks/` regenerates per-day; `docs/data/all.json.gz` is one
  bundled file overwritten daily.** Stale per-ticker pages are removed
  by set-difference (Path-based, guarded by
  `target.resolve().is_relative_to(DOCS.resolve())`), not blanket
  `rm -rf`. See Phase 2 generate_site.py spec.
- **`docs/notes/` is append-only.** Each day adds one HTML file.
- **`data/cache/` is gitignored** — recreated each run.
- **Parquet cache keyed by date.** If workflow re-runs same day,
  `fetch_prices.py` is idempotent (overwrites the day's parquet);
  `compute_screens.py` and `generate_site.py` re-derive from parquet
  deterministically.

### API Surface Parity

The "API" here is the URL surface served by GH Pages. Every URL is
re-rendered each day:

- `/index.html` — daily
- `/stocks/<TICKER>.html` — only if ticker is in today's screen
- `/data/all.json.gz` — regenerated daily; indexes all screened tickers
- `/notes/<DATE>.html` — appended once per day
- `/about.html` — only on phase 5 deploy, then static
- `/assets/*` — committed once, served as-is

Anything that links to `/stocks/<TICKER>.html` must check membership
in today's screen first, or accept 404 risk.

### Integration Test Scenarios

| Scenario | Expected behavior |
|---|---|
| **Run on non-trading-day (Memorial Day Mon)** | Workflow fires, `compute_screens.py` detects via `pandas_market_calendars`, writes flag, banner renders, no run CSV duplicated; `docs/data/` unchanged |
| **Ticker with 4 days of history (recent IPO)** | Skipped silently; logged |
| **Ticker triggers all 3 definitions** | All 3 badges green; appears in screen |
| **Ticker triggers only Range** | Range badge green; other two grey; appears in screen |
| **Bucket-B ticker on day after 2-for-1 split** | `auto_adjust` divides historical prices; variation reads as small; ticker correctly NOT in screen |
| **GH Actions delayed 60 min** | Workflow fires at ~12:30 UTC, still completes before 9:30am ET market open |
| **Two workflow runs overlap** | `concurrency: refresh-data` queues the second |
| **Universe shrinks by 200 names (delistings)** | `fetch_prices.py` logs misses, screen runs on whatever's left |

## Acceptance Criteria

### Functional

- [x] Bucket A screen returns tickers in $300–$800 with ≥1 of 3
      variation triggers and ≥$1M avg dollar volume
- [x] Bucket B screen returns tickers in $0.79–$20 with ≥1 of 3
      variation triggers and ≥$1M avg dollar volume
- [ ] Index page renders two sortable, searchable tables
- [ ] Each row links to a per-stock detail page
- [ ] Each detail page renders a candlestick + volume chart with 1M /
      6M / 1Y toggle
- [ ] Bucket B detail charts default to log y-axis
- [ ] Daily note appears at `docs/notes/<DATE>.html` summarizing
      notable names + diff vs yesterday
- [ ] About page explains the three formulas with LaTeX rendering
- [ ] Footer shows "as of <ET timestamp>" and disclaimer
- [ ] Site refreshes daily Mon–Fri before US market open without
      manual intervention

### Non-functional

- [ ] Index page first-contentful-paint <1s on a 4G connection
- [ ] Detail-page chart renders in <500ms after JSON load
- [ ] Total daily commit <5MB
- [ ] GH Actions run time <15 minutes p95
- [ ] All pages mobile-readable at 375px width
- [ ] Site works without JS for tables (graceful degradation: shows
      unsorted but readable HTML)
- [ ] No secrets in repo; PAT lives only in Claude routine env

### Quality gates

- [x] `python -m py_compile scripts/*.py` passes
- [x] One end-to-end local dry run on 50-ticker test universe succeeds
- [ ] One `workflow_dispatch` run succeeds before scheduled deploy
- [ ] README screenshots match live site
- [ ] PAT scoped to single repo, `contents: write` only

## Success Metrics

- **Reliability:** site refresh succeeds ≥98% of trading days over the
  first 90 days (≥51 of 52 successful runs)
- **Latency:** site visibly updated by 9:00 AM ET on ≥95% of trading
  days
- **Coverage:** screen returns ≥5 names in Bucket A and ≥10 names in
  Bucket B on at least 80% of trading days
- **Personal usage:** Shehral references the screener as part of his
  market-prep routine — measured informally

## Dependencies & Prerequisites

- GitHub account with public repo creation
- Anthropic API key (already in use for Claude routines)
- Claude agents cloud access (already configured per CLAUDE.md)
- No paid data subscriptions

## Risk Analysis & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **yfinance Yahoo API breaks** | Medium (it's unofficial) | High (whole screen down) | `yf.config.network.retries=3`; fall back to `curl_cffi` session if TLS fingerprinting becomes the issue; long-term backup plan: switch to Financial Modeling Prep free tier |
| **GH Actions cron drift >2hr** | Low | Medium (refresh after market open) | 11:30 UTC has ~4hr buffer to 9:30am ET; off-the-hour cron reduces drift further; even worst-case still pre-market |
| **Universe file format changes** | Very low | Medium | NASDAQ Trader format is stable since ~2005; parser is one screenful of code |
| **Lightweight Charts v6 breaking change** | Medium | Low | Pin to `v5.2.0` in committed asset; upgrade deliberately |
| **PAT leak** | Low | Medium | Fine-grained PAT, scoped to single repo, `contents: write` only, 90-day rotation |
| **Stock split fakes the variation signal** | Low | Low | `auto_adjust=True` (default) divides historicals correctly |
| **Pump-and-dump in Bucket B** | High (penny stocks) | Low for screen itself, High if someone trades on it | $1M volume floor; disclaimer prominent; about page emphasizes "screen ≠ recommendation" |
| **Repo storage explosion from runs/** | Very low | Low | 1.3MB/year; far below GH limits |
| **GH Pages outage** | Very low | Low | Site is static; can re-deploy elsewhere instantly |
| **NYSE holiday calendar gap** | Low | Low | `pandas_market_calendars` maintained; cross-check vs Yahoo's own holiday list |

## Resource Requirements

- **Time:** 5 focused work sessions (≈ 5 hours each) = 25 hours total
  for v1
- **Infrastructure:** $0 (GH Actions free for public repos, GH Pages
  free, yfinance free, Anthropic API <$5/yr)
- **Maintenance:** ~10 min/week to glance at the site, ~30 min/quarter
  to rotate the PAT and check yfinance still works

## Future Considerations

- **v2: Persistent detail pages.** Backfill `docs/stocks/<TICKER>.html`
  from `data/runs/` history so links from old notes resolve. Add a
  "last seen in screen on <date>" badge for stale pages.
- **v2: Custom alerts.** RSS feed of new entries to a bucket.
- **v2: Sector breakdown.** Bar chart of today's screened names by
  GICS sector.
- **v3: Backtest harness.** "If we'd bought everything in Bucket A on
  signal and held N days, what's the realized return?" Educational, not
  tradeable.
- **v3: Sparkline column in index table.** 5-day sparkline per row
  without needing to click into the detail page.
- **v3: Search across history.** "When was AAPL last in Bucket A?"
- **v3: Toggle Bucket A log scale.** User preference, persisted to
  `localStorage`.

## Documentation Plan

- `README.md` — what + why + how + disclaimer
- `docs/about.html` — math, methodology, limitations (user-facing)
- Code: docstrings on each script entry point only; otherwise no
  comments (per global rule)
- This plan doc — preserved as the source of truth for v1

## Frontend Design Tokens (full set)

**Source:** frontend-design skill applied via general-purpose agent.
The "feel" is **indie-research terminal with FT polish** — not Bloomberg
(too sparse/hostile), not Robinhood (too consumer-soft). Think
"Stratechery meets a Reuters Eikon side-panel." Tables = terminal mode,
notes = magazine mode; the contrast between them is the memorable thing.

### Typography

```css
/* Display / headings — used at h1/h2 and notes pages only */
font-family: 'Fraunces', serif;
font-variation-settings: 'opsz' 144, 'SOFT' 100;

/* Body / UI */
font-family: 'Geist', system-ui, sans-serif;   /* not Inter — too overused */

/* Numerics (load-bearing — every price, %, variation value) */
font-family: 'JetBrains Mono', monospace;
font-feature-settings: 'tnum' 1, 'zero' 1;
```

**Scale (minor third 1.200):** 12 / 13 / 14 / 16 / 19 / 23 / 28 / 36 / 56 px.
- Body 14px on tables, 16px on dashboards, 19px on notes pages.
- Line-height 1.15 in tables, 1.45 dashboard, 1.7 notes.
- Weights: 400 body, 500 column labels, 700 numerics on row's *primary*
  variation only (never bold a whole row).

### Color tokens (dark default)

```css
--bg-0:    #0B0D10;   /* page */
--bg-1:    #11141A;   /* card */
--bg-2:    #181C24;   /* row hover, table header */
--border:  #232833;
--text-hi: #E8EAED;
--text-md: #A4ACB9;
--text-lo: #5C6573;
--up:      #4ADE80;   /* green, WCAG AA on bg-0 */
--down:    #F87171;
--neutral: #94A3B8;
--trigger: #F5C451;   /* amber, badge fill */
--accent:  #7DD3FC;   /* sky — links, focus rings, sparkline */
```

**Light mode** (`@media (prefers-color-scheme: light)`): flip bg to
`#FAFAF7` (warm paper, not pure white), text to `#16181D`, dim `--up` to
`#16A34A` and `--down` to `#DC2626`. **Never use pure white** — financial
sites that do feel like spreadsheets.

Numbers carry color, not background fills. Triggered badges = `--trigger`
filled chip; untriggered = `--text-lo` outlined chip (dimmed, not hidden
— readers should see what *didn't* trigger too).

### Hierarchy & spacing

- 8px base grid; component padding `4 / 8 / 12 / 16 / 24 / 40 / 64`.
- Index page: max-width 1440px, gutter 24px. Two tables stacked, each
  preceded by a one-line `Range | 5-day return | Max daily move` legend.
  No card wrapper — hairline `1px solid --border` above each table.
- Per-stock dashboard: 12-col grid. Header full width; three variation
  cards in a 3-col row (each 280px min); chart 8-col + stats 4-col;
  links inline footer.
- Variation cards: tall ticker-style with metric in 36px tabular,
  formula in 12px `--text-lo` below.
- Notes page: 640px measure, centered, dateline at top in small caps
  tracking `0.08em`.

### Mobile (≤375px)

Tables are the hard problem. **Do not horizontally scroll a 10-col
table** — that's the lazy answer. Use Tabulator's
`responsiveLayout: 'collapse'` with a custom collapsed renderer: each
row becomes a 2-line micro-card. Line 1 = `TICKER  $price  ±change%`,
line 2 = three tiny mono pills showing only the *triggered* variations.
Tap expands the row to reveal the full column set inline (accordion).
Sort controls become a single `<select>` dropdown above the table at
<640px.

Dashboard mobile: variation cards stack vertically; chart goes
full-bleed edge-to-edge (negative horizontal margin) to maximize plot
area; toggle (1M/6M/1Y) becomes a segmented control pinned below the
chart, not above.

Breakpoints: `375 / 640 / 960 / 1280`. Below 375, allow horizontal
scroll on the chart only.

### Memorable detail (the screenshot moment)

A **1px-tall sparkline strip** rendered behind each table row's ticker
cell — 5-day close in `--accent` at 30% opacity, no axes. Costs no row
height; conveys the *shape* of the move before the reader processes the
numbers. Implement via inline SVG generated server-side in
`generate_site.py`, embedded as a `background-image: url("data:image/svg+xml,...")`
in the ticker cell. ~200 bytes per row.

## Operational Playbook

**Source:** deployment-verification-agent. Compressed checklist for v1
launch and first-week ops.

### Pre-deploy verification (before first `workflow_dispatch`)

**Repo & Pages**
- [ ] Repo is **public** (`shehral/weekly-movers`) — required for free
      Actions + Pages
- [ ] Settings → Pages → Source: `Deploy from a branch`, Branch:
      `main`, Folder: `/docs`
- [ ] `docs/index.html` placeholder committed so Pages has something
      to serve before first cron run
- [ ] Settings → Actions → General → Workflow permissions: **Read and
      write** (else `git push` 403s)
- [ ] Settings → Security → Code security: **Secret scanning + push
      protection** enabled
- [ ] Settings → Security → Code security: **Dependabot alerts**
      enabled

**Workflow file sanity**
- [ ] `.github/workflows/refresh-data.yml` has `permissions: contents:
      write` and `workflow_dispatch:` trigger
- [ ] Cron is quoted: `'30 11 * * 1-5'`
- [ ] `concurrency: writeback` set, `cancel-in-progress: false`
- [ ] `timeout-minutes: 30` present
- [ ] `pip install --require-hashes -r requirements.lock`

**Repo hygiene**
- [ ] `.gitignore` excludes `data/cache/`, `.venv/`, `__pycache__/`
- [ ] No secrets in history: `git log -p | grep -iE 'sk-ant|ghp_|github_pat_'`
      returns empty
- [ ] `data/universe.csv` committed so first non-Monday run doesn't
      refetch
- [ ] `requirements.lock` pins `yfinance==<exact>` and includes hashes

**Local dry-run done**
- [ ] `python scripts/compute_screens.py` produced a valid CSV on
      50-ticker test set
- [ ] `python -m py_compile scripts/*.py` clean
- [ ] Attempted-XSS test on narrative pipeline passes (Phase 4 only)

### First-run validation (after `workflow_dispatch` succeeds)

Inspect the new commit:

- [ ] `data/runs/<TODAY>.csv` exists; `wc -l` ≥ 15 rows (Bucket A ≥3,
      Bucket B ≥10)
- [ ] CSV has all expected columns; no rows with all three
      `*_value` cols NULL
- [ ] `last_close` in [300, 800] for every Bucket A row; in [0.79, 20]
      for Bucket B
- [ ] `avg_dollar_vol` ≥ 1_000_000 for every row
- [ ] At least one `*_triggers` column = `True` per row
- [ ] `docs/stocks/<TICKER>.html` count == row count in run CSV
- [ ] `docs/data/all.json.gz` exists and is <500KB
- [ ] Visit `https://shehral.github.io/weekly-movers/`: both tables
      render and sort; click 3 random tickers → chart loads,
      timeframe toggle works, Bucket B is log-scale by default
- [ ] Footer "as of" timestamp matches today ET; disclaimer visible
- [ ] Spot-check 2 tickers' `range_value` against Yahoo Finance 5-day
      high/low

### Rollback (first scheduled run broken)

1. **Disable cron immediately**: Settings → Actions → General →
   Disable Actions, OR push a commit removing the `schedule:` block
2. `git revert <bad-commit-sha>` on main; push. Pages redeploys prior
   `docs/` in ~60s
3. If `data/runs/<DATE>.csv` is corrupt but `docs/` is fine:
   `git rm data/runs/<DATE>.csv && git commit && git push`
4. If yfinance is the culprit: pin to last-known-good version in
   `requirements.lock`, push, re-dispatch
5. Re-enable cron only after one successful `workflow_dispatch`

### Day-7 failure signals (no APM)

| Signal | Where | "Broken" threshold |
|---|---|---|
| Workflow run status | Actions tab badge | 2+ consecutive red |
| Last commit timestamp | repo home | No `data-bot` commit on a trading day by 12:30 UTC |
| Run-CSV row count trend | `git log -p data/runs/` | Drops to 0 / stays <5 for 2+ days |
| Site "as of" timestamp | live site footer | Stale by >24h on a trading day |
| Narrative commit | `docs/notes/<DATE>.html` | Missing 2 days in a row |
| Repo size | Settings → repo overview | Jumps >50MB |
| GH Pages build status | Actions → `pages-build-deployment` | Red |

Calendar reminder day-80 to rotate the 90-day PAT (or wait for the
expiry workflow to open an issue).

### First-week morning ops (Mon–Fri ~8am ET)

Each weekday during week 1, ~3 minutes:

- [ ] Actions tab → today's `Refresh screener data` run is green
- [ ] Live site → "as of" timestamp is today; row counts non-zero in
      both buckets
- [ ] Click one random ticker — detail page + chart render
- [ ] `docs/notes/<TODAY>.html` exists after ~12:30 UTC; diff section
      names real tickers
- [ ] Skim run log for `WARN`/`ERROR` (`YFRateLimitError`,
      empty-ticker counts)
- [ ] Mon only: `data/universe.csv` updated
- [ ] Note anomalies in a `docs/ops/week1.md` scratch log

If any check fails twice in week 1, treat that pipeline as unreliable
and add a retry step or fallback before week 2.

## Aggressive YAGNI Fallback (escape hatch)

**Decision rule:** if Phase 1 takes >10 hours, drop scope to: one
`run.py` script + one workflow yml + README, ~6 files. Cut: Jinja2,
`_common.py`, Pipeline 2 (narrative), `about.html` with KaTeX,
Tabulator.js, holiday banner, mobile QA, README screenshot, custom
domain. Keep: three variation formulas, `$1M` volume floor, parquet
cache, yfinance 80-chunk + curl_cffi, Lightweight Charts v5,
`auto_adjust=True`, off-the-hour cron, push-rebase loop, atomic
writes. ~10 hours instead of ~25. Source: code-simplicity-reviewer.
Not applied to the primary plan because Shehral chose the full
feature set; preserved as a known-good minimum if pace slips.

## Sources & References

### Origin

- **Brainstorm document:** [`docs/brainstorms/2026-05-25-stock-screener-brainstorm.md`](../brainstorms/2026-05-25-stock-screener-brainstorm.md)
- Key decisions carried forward:
  1. Three variation definitions, OR-combined inclusion, side-by-side display
  2. `$1M` 30-day average dollar volume floor on both buckets
  3. Trailing 5 trading-day rolling window (not calendar week)
  4. yfinance + NYSE/NASDAQ listed universe (no OTC)
  5. Split-pipeline architecture: GH Actions for data, Claude routine for narrative
  6. TradingView Lightweight Charts v5 with toggleable timeframes; log axis for Bucket B

### External references

**Core libraries**
- yfinance docs: https://ranaroussi.github.io/yfinance/ — verified
  current API surface (`auto_adjust=True` default,
  `yf.config.network.retries`, `yf.download(period=..., threads=True)`)
- yfinance #2422 — rate limit:
  https://github.com/ranaroussi/yfinance/issues/2422
- yfinance #2614 — bulk download rate limit:
  https://github.com/ranaroussi/yfinance/issues/2614
- yfinance #2633 — curl_cffi SSL:
  https://github.com/ranaroussi/yfinance/issues/2633
- QuantVPS yfinance migration guide:
  https://www.quantvps.com/blog/yahoo-finance-api-documentation
- Why yfinance Keeps Getting Blocked (Medium, 2025):
  https://medium.com/@trading.dude/why-yfinance-keeps-getting-blocked-and-what-to-use-instead-92d84bb2cc01
- TradingView Lightweight Charts v5.2 docs:
  https://tradingview.github.io/lightweight-charts/
- Tabulator v6.4: https://tabulator.info/docs/6.4
- NASDAQ Trader symbol files:
  https://www.nasdaqtrader.com/dynamic/symdir/
- pandas_market_calendars:
  https://pandas-market-calendars.readthedocs.io/
- bleach: https://bleach.readthedocs.io/
- Jinja2 autoescape:
  https://jinja.palletsprojects.com/en/3.1.x/api/#autoescaping

**GitHub Actions / Pages**
- GitHub Actions cron syntax:
  https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#schedule
- GitHub Pages from `/docs`:
  https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site
- GH community discussion #146923 — top-of-hour cron drift:
  https://github.com/orgs/community/discussions/146923
- GH community discussion #156282 — April 2025 cron delays:
  https://github.com/orgs/community/discussions/156282
- crontap — GH Actions cron drift analysis:
  https://crontap.com/blog/github-actions-cron-drift-problem
- stefanzweifel/git-auto-commit-action:
  https://github.com/stefanzweifel/git-auto-commit-action
- 2025 GH Actions best practices (Suzuki):
  https://suzuki-shunsuke.github.io/slides/github-actions-best-practice-2025

**Standards & conventions**
- Usercentrics 2025 disclaimer examples (for "not financial advice"
  boilerplate):
  https://usercentrics.com/guides/website-disclaimers/disclaimer-examples/
- WCAG 2.2 AA — color contrast + semantic tables:
  https://www.w3.org/WAI/WCAG22/quickref/?currentsidebar=%23col_overview&versions=2.2&levels=aa

### Related work

- CLAUDE.md global rules (volume-floor reasoning, no-OTC for $0.79
  floor, log-scale convention for penny chart) — all applied
- Theoria taste profile (aggressive risk, beginner in quant finance) —
  reflected in extensive about-page methodology explanation

## Next Steps

After plan acceptance:
- `/ce:work` to start Phase 1 implementation, OR
- `/deepen-plan` for one more layer of research detail on yfinance
  reliability + GH Actions cron drift patterns, OR
- `/technical_review` to stress-test this plan before any code is
  written
