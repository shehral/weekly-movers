# Weekly Movers

A daily-refreshed US equity screen for two volatility buckets, published as a
public GitHub Pages site. Built as a transparent, reproducible alternative to
sign-up-gated commercial screeners.

**Live site:** https://shehral.github.io/weekly-movers/ (after Phase 3 deploy)

## What it surfaces

| Bucket | Price range | Variation threshold | Catches |
|---|---|---|---|
| **A — Mid-priced movers** | $300 – $800 | ≥ $15 weekly | Volatile mid-caps |
| **B — Penny movers** | $0.79 – $20 | ≥ 20% weekly | Penny / small-cap momentum |

Both buckets require ≥ $1M average daily dollar volume.

## How "weekly variation" is computed

For trailing 5 trading sessions. A stock qualifies if **any one** is true.

| Name | Bucket A | Bucket B |
|---|---|---|
| **Range** | max(High) − min(Low) ≥ $15 | max(High)/min(Low) − 1 ≥ 0.20 |
| **5-day return** | \|Close[t] − Close[t−5]\| ≥ $15 | \|Close[t]/Close[t−5] − 1\| ≥ 0.20 |
| **Max daily** | max\|daily ΔClose\| ≥ $15 | max\|daily pctΔClose\| ≥ 0.20 |

Each row shows all three numerical values plus three triggered/untriggered
badges. The site footer renders these formulas as plain text.

## Architecture

```
GitHub Actions cron (Mon–Fri, 11:30 UTC ≈ pre-market ET)
  ├─ Polygon Grouped Daily Bars: 35 days × all US stocks (35 API calls)
  ├─ Compute screen (3 variation metrics, OR-combined, vol filter)
  ├─ yfinance: 1Y history for the ~500 screened tickers (under rate-limit wall)
  ├─ Generate static site: docs/index.html + docs/stocks/*.html + bundled OHLC
  └─ Commit & push (rebase-retry loop)
                ↓
        GitHub Pages serves docs/
```

Two data providers, each used where they excel:
- **Polygon.io free tier** for the universe-wide screen data (one API call
  returns OHLC for *every* US stock for a given date — sidesteps Yahoo's
  per-ticker rate limit at scale)
- **yfinance** for the per-stock chart history (≤ 600 screened tickers stays
  well under Yahoo's 1,300-ticker rate-limit wall)

## Local dev

```bash
git clone https://github.com/shehral/weekly-movers
cd weekly-movers

uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.lock --require-hashes

export POLYGON_API_KEY="<your-key>"   # https://polygon.io/, free tier is enough

# One-shot end-to-end (run the four scripts in order):
.venv/bin/python scripts/fetch_universe.py       # NASDAQ + NYSE common stock universe
.venv/bin/python scripts/fetch_prices.py         # 35 days OHLC via Polygon (~7 min)
.venv/bin/python scripts/compute_screens.py      # writes data/runs/<DATE>.csv
.venv/bin/python scripts/fetch_chart_history.py  # 1Y history for screened tickers (~30s)
.venv/bin/python scripts/generate_site.py        # render docs/

# Serve the site locally:
cd docs && python3 -m http.server 8765
# open http://localhost:8765/
```

For a quick 50-ticker test universe (no Polygon needed for the fetch_universe
step):

```bash
.venv/bin/python scripts/fetch_universe.py --test
```

## Repository layout

```
weekly-movers/
├── .github/workflows/refresh-data.yml   # daily cron
├── scripts/
│   ├── _common.py                       # paths, ET clock, Pydantic ScreenRow, CIK lookup
│   ├── _polygon.py                      # Polygon Grouped Daily Bars adapter
│   ├── fetch_universe.py
│   ├── fetch_prices.py                  # screen data via Polygon
│   ├── fetch_chart_history.py           # chart data via yfinance
│   ├── compute_screens.py
│   └── generate_site.py
├── templates/{base,index,stock}.html.j2
├── data/
│   ├── universe.csv                     # weekly refresh, committed
│   ├── runs/<DATE>.csv                  # daily screen output, committed (history)
│   ├── cache/<DATE>.parquet             # gitignored
│   └── sec_tickers.json                 # 7-day cached ticker→CIK mapping
├── docs/                                # GitHub Pages root
│   ├── index.html
│   ├── about.html
│   ├── stocks/<TICKER>.html
│   ├── data/all.json                    # bundled OHLC for screened tickers
│   └── assets/                          # Lightweight Charts, Tabulator, fonts
├── todos/                               # planning artifacts from /ce review pipeline
└── requirements.{txt,lock}
```

## Configuration

- `POLYGON_API_KEY` — Polygon.io API key, free tier sufficient. In CI: GitHub
  Actions secret. Locally: `~/.weekly-movers-env` (mode 600, outside repo).

## Disclaimer

**Not financial advice.** This is a descriptive screen — it surfaces names with
recent price variation. Nothing here is a recommendation to buy, sell, or hold
any security. Past performance is not indicative of future results. Data may be
delayed or inaccurate. Do your own research and consult a licensed advisor
before making decisions.

## License

MIT — see `LICENSE`. The project plan and design artifacts are under
`docs/plans/` and `docs/brainstorms/`.

## Acknowledgements

- [Polygon.io](https://polygon.io) — Grouped Daily Bars API
- [yfinance](https://github.com/ranaroussi/yfinance) — Yahoo Finance Python client
- [TradingView Lightweight Charts](https://tradingview.github.io/lightweight-charts/) — chart rendering
- [Tabulator](https://tabulator.info/) — interactive tables
- [Fraunces](https://fonts.google.com/specimen/Fraunces) + [JetBrains Mono](https://www.jetbrains.com/lp/mono/) — typography
