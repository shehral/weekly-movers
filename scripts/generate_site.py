"""Render the static site: index.html + per-stock detail pages + bundled OHLC JSON.

- index.html: two Tabulator tables with inline JSON data (no AJAX)
- stocks/<TICKER>.html: per-stock dashboard with chart skeleton
- data/all.json: bundled OHLC for all screened tickers (loaded by chart JS)
- about.html: static-ish methodology page

Staleness guard: delete docs/stocks/<TICKER>.html files NOT in today's
screen via set-difference, using Path-based deletion guarded by
is_relative_to(DOCS).
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from _common import (
    CACHE,
    DOCS,
    ROOT,
    RUNS,
    atomic_write_text,
    get_logger,
    is_trading_day,
    load_ticker_to_cik,
    safe_resolve_under,
    today_et,
)

log = get_logger("generate_site")
TEMPLATES = ROOT / "templates"

env = Environment(
    loader=FileSystemLoader(str(TEMPLATES)),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _load_run(asof: date) -> pd.DataFrame:
    path = RUNS / f"{asof.isoformat()}.csv"
    return pd.read_csv(path, comment="#")


def _load_chart_history(asof: date) -> pd.DataFrame:
    path = CACHE / f"chart_history_{asof.isoformat()}.parquet"
    if not path.exists():
        log.warning("Chart history parquet missing: %s — charts will be empty", path)
        return pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume"])
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _row_to_dict(row: pd.Series) -> dict:
    return {k: (str(v) if not isinstance(v, (int, float, bool)) else v) for k, v in row.items()}


def _build_chart_bundle(history: pd.DataFrame, tickers: list[str]) -> dict[str, list[dict]]:
    """Bundle OHLC as { ticker: [{time, o, h, l, c, v}, ...] }. time = YYYY-MM-DD string."""
    if history.empty:
        return {ticker: [] for ticker in tickers}
    bundle: dict[str, list[dict]] = {}
    grouped = history.groupby("ticker", sort=False)
    keep = set(tickers)
    for ticker, df in grouped:
        if ticker not in keep:
            continue
        df = df.sort_values("date")
        bundle[ticker] = [
            {
                "time": d.strftime("%Y-%m-%d"),
                "o": round(float(o), 4),
                "h": round(float(h), 4),
                "l": round(float(l), 4),
                "c": round(float(c), 4),
                "v": int(v),
            }
            for d, o, h, l, c, v in zip(
                df["date"], df["open"], df["high"], df["low"], df["close"], df["volume"]
            )
        ]
    # Ensure every screened ticker has an entry (even if empty)
    for ticker in tickers:
        bundle.setdefault(ticker, [])
    return bundle


def _build_sparkline(closes: list[float], width: int = 56, height: int = 14) -> str:
    """Return an inline SVG path string for a sparkline of the last N closes.

    Uses --accent at 35% opacity for the line; no axes, no labels. Designed
    to sit behind/beside the ticker cell in the index table.
    """
    if len(closes) < 2:
        return ""
    lo = min(closes)
    hi = max(closes)
    span = hi - lo
    if span == 0:
        return ""
    n = len(closes)
    pts = []
    for i, c in enumerate(closes):
        x = round(i * (width - 1) / (n - 1), 2)
        y = round((height - 1) - (c - lo) * (height - 1) / span, 2)
        pts.append(f"{x},{y}")
    polyline = " ".join(pts)
    last_color = "#4ADE80" if closes[-1] >= closes[0] else "#F87171"
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'aria-hidden="true" style="vertical-align: middle; opacity: 0.85;">'
        f'<polyline points="{polyline}" fill="none" stroke="{last_color}" '
        f'stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )


def _sparkline_for_ticker(bundle: dict[str, list[dict]], ticker: str, n_days: int = 30) -> str:
    candles = bundle.get(ticker, [])
    if not candles:
        return ""
    closes = [c["c"] for c in candles[-n_days:]]
    return _build_sparkline(closes)


def _format_variation(row: pd.Series) -> tuple[str, str, str]:
    if row["bucket"] == "A":
        rng = f"${Decimal(str(row['range_value'])):.2f}"
        ret = f"${Decimal(str(row['ret_5d_value'])):.2f}"
        daily = f"${Decimal(str(row['max_daily_value'])):.2f}"
    else:
        rng = f"{Decimal(str(row['range_value'])) * 100:.1f}%"
        ret = f"{Decimal(str(row['ret_5d_value'])) * 100:.1f}%"
        daily = f"{Decimal(str(row['max_daily_value'])) * 100:.1f}%"
    return rng, ret, daily


def _truthy(v) -> bool:
    return v is True or str(v).lower() == "true"


def _row_for_template(row: pd.Series) -> dict:
    d = row.to_dict()
    d["range_triggers"] = _truthy(d.get("range_triggers"))
    d["ret_5d_triggers"] = _truthy(d.get("ret_5d_triggers"))
    d["max_daily_triggers"] = _truthy(d.get("max_daily_triggers"))
    return d


def _clean_for_json(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if pd.isna(value):
        return None
    return value


def _row_for_table(row: pd.Series) -> dict:
    """Lighter version for the inline JSON in index.html — no need for sector etc."""
    d = {k: _clean_for_json(v) for k, v in row.to_dict().items()}
    for key in ("range_triggers", "ret_5d_triggers", "max_daily_triggers"):
        d[key] = _truthy(d.get(key))
    return d


def _delete_stale_stock_pages(active_tickers: set[str]) -> int:
    stocks_dir = DOCS / "stocks"
    if not stocks_dir.exists():
        return 0
    deleted = 0
    for path in stocks_dir.iterdir():
        if path.suffix != ".html":
            continue
        ticker = path.stem
        if ticker in active_tickers:
            continue
        safe = safe_resolve_under(path, DOCS)
        safe.unlink()
        deleted += 1
    return deleted


def _write_index(rows_a: list[pd.Series], rows_b: list[pd.Series],
                  context: dict, bundle: dict[str, list[dict]]) -> None:
    def _augment(rows):
        out = []
        for r in rows:
            d = _row_for_table(r)
            d["spark"] = _sparkline_for_ticker(bundle, str(r["ticker"]))
            out.append(d)
        return out
    data_a = _augment(rows_a)
    data_b = _augment(rows_b)
    ctx = {
        **context,
        "bucket_a_rows": rows_a,
        "bucket_b_rows": rows_b,
        "bucket_a_json": json.dumps(data_a, default=str, allow_nan=False),
        "bucket_b_json": json.dumps(data_b, default=str, allow_nan=False),
        "asset_root": ".",
    }
    out = DOCS / "index.html"
    atomic_write_text(out, env.get_template("index.html.j2").render(**ctx))
    log.info("Wrote %s (%d A, %d B)", out, len(rows_a), len(rows_b))


def _write_stock_pages(all_rows: list[pd.Series], context: dict, cik_map: dict[str, str]) -> None:
    stocks_dir = DOCS / "stocks"
    stocks_dir.mkdir(parents=True, exist_ok=True)
    template = env.get_template("stock.html.j2")
    matched = 0
    for row in all_rows:
        rng_d, ret_d, daily_d = _format_variation(row)
        cik = cik_map.get(str(row["ticker"]).upper())
        if cik:
            matched += 1
        ctx = {
            **context,
            "row": _row_for_template(row),
            "range_display": rng_d,
            "ret_display": ret_d,
            "daily_display": daily_d,
            "cik": cik,
            "asset_root": "..",
        }
        out = stocks_dir / f"{row['ticker']}.html"
        atomic_write_text(out, template.render(**ctx))
    log.info("Wrote %d stock pages (%d with SEC CIK)", len(all_rows), matched)


def _write_chart_data(bundle: dict, asof: date) -> None:
    out_dir = DOCS / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "all.json"
    atomic_write_text(out, json.dumps(bundle, default=str, separators=(",", ":")))
    size_kb = out.stat().st_size // 1024
    log.info("Wrote %s (%d tickers, %d KB)", out, len(bundle), size_kb)


def _write_about(context: dict) -> None:
    template = env.get_template("about.html.j2")
    out = DOCS / "about.html"
    atomic_write_text(out, template.render(**context, asset_root="."))
    log.info("Wrote %s", out)


def _write_notes_index(context: dict) -> None:
    notes_dir = DOCS / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    notes = []
    for path in sorted(notes_dir.glob("*.html"), reverse=True):
        if path.stem == "index":
            continue
        notes.append({"date": path.stem})
    template = env.get_template("notes_index.html.j2")
    out = notes_dir / "index.html"
    atomic_write_text(out, template.render(**context, notes=notes, asset_root=".."))
    log.info("Wrote %s (%d notes listed)", out, len(notes))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asof", type=str, default=None)
    args = parser.parse_args()
    asof = today_et() if args.asof is None else date.fromisoformat(args.asof)

    run = _load_run(asof)
    if run.empty:
        log.error("Empty run CSV for %s", asof)
        return 2
    log.info("Loaded %d screen rows for %s", len(run), asof)

    rows_a = [row for _, row in run[run["bucket"] == "A"].iterrows()]
    rows_b = [row for _, row in run[run["bucket"] == "B"].iterrows()]
    all_rows = rows_a + rows_b
    active_tickers = {r["ticker"] for r in all_rows}

    history = _load_chart_history(asof)
    bundle = _build_chart_bundle(history, sorted(active_tickers))

    last_session = pd.to_datetime(run["last_session_date"]).max().date()
    context = {
        "as_of": asof.isoformat(),
        "universe_size": "6,500+",
        "screen_size": len(run),
        "markets_closed_today": not is_trading_day(asof),
        "last_session": last_session.isoformat(),
    }

    DOCS.mkdir(parents=True, exist_ok=True)
    deleted = _delete_stale_stock_pages(active_tickers)
    if deleted:
        log.info("Deleted %d stale stock pages", deleted)

    cik_map = load_ticker_to_cik()
    _write_chart_data(bundle, asof)
    _write_index(rows_a, rows_b, context, bundle)
    _write_stock_pages(all_rows, context, cik_map)
    _write_about(context)
    _write_notes_index(context)
    log.info("Site generated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
