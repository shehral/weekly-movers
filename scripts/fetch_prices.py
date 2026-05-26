"""Fetch trailing-N-day OHLC for the universe via Polygon.io.

Uses Grouped Daily Bars endpoint: one API call per trading day returns
OHLC for every US stock. Free-tier safe (5 calls/min, sleep 12.5s
between).

Output schema unchanged from prior yfinance version: parquet of
(ticker, date, open, high, low, close, volume) rows, written atomically.
A SHA256 of the parquet bytes is exposed so compute_screens.py can
record it in the run-CSV header for staleness detection.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from _common import (
    CACHE,
    NYSE,
    UNIVERSE_CSV,
    atomic_write_bytes,
    get_logger,
    today_et,
)
from _polygon import fetch_many_days

DEFAULT_DAYS = 35  # 5 sessions for variation + 30 sessions avg vol + buffer

log = get_logger("fetch_prices")


def last_n_trading_days(n: int, asof: date | None = None) -> list[date]:
    asof = asof or today_et()
    schedule = NYSE.valid_days(start_date=asof - pd.Timedelta(days=n * 2), end_date=asof)
    days = [d.date() for d in schedule[-n:]]
    return days


def write_parquet_atomic(df: pd.DataFrame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, buf, compression="zstd")
    data = buf.getvalue()
    sha = hashlib.sha256(data).hexdigest()
    atomic_write_bytes(path, data)
    return sha


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
                        help=f"Trading days of history to fetch (default {DEFAULT_DAYS})")
    parser.add_argument("--asof", type=str, default=None,
                        help="ISO date to use as 'today' (default: today_et)")
    parser.add_argument("--limit-universe", type=int, default=None,
                        help="Cap universe size after intersect (for testing)")
    args = parser.parse_args()

    if not UNIVERSE_CSV.exists():
        log.error("Universe missing: %s. Run fetch_universe.py first.", UNIVERSE_CSV)
        return 2

    asof = today_et() if args.asof is None else date.fromisoformat(args.asof)
    universe = pd.read_csv(UNIVERSE_CSV)
    universe_set = set(universe["symbol"].str.upper())
    log.info("Universe: %d tickers", len(universe_set))

    days = last_n_trading_days(args.days, asof=asof)
    log.info("Fetching %d trading days: %s … %s", len(days), days[0], days[-1])

    raw = fetch_many_days(days)
    if raw.empty:
        log.error("Polygon returned no data across %d days", len(days))
        return 3

    log.info("Polygon returned %d rows across %d tickers (universe: %d)",
             len(raw), raw["ticker"].nunique(), len(universe_set))

    # Intersect Polygon coverage with our common-stock universe
    raw["ticker"] = raw["ticker"].str.upper()
    df = raw[raw["ticker"].isin(universe_set)].copy()
    if args.limit_universe:
        keep = list(sorted(df["ticker"].unique()))[: args.limit_universe]
        df = df[df["ticker"].isin(keep)]
    log.info("After universe intersect: %d rows × %d tickers",
             len(df), df["ticker"].nunique())

    df = df.dropna(subset=["close", "volume"]).reset_index(drop=True)
    out = CACHE / f"{asof.isoformat()}.parquet"
    sha = write_parquet_atomic(df, out)
    log.info("Wrote %s (%d rows, sha256: %s)", out, len(df), sha[:12])
    return 0


if __name__ == "__main__":
    sys.exit(main())
