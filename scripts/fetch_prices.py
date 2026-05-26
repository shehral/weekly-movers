"""Batch-download trailing 1y OHLC for the full universe via yfinance.

Applies todos/003 idioms: tenacity retries, curl_cffi session, atomic
parquet write. Single 1y pass serves both screen logic and chart data.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import sys
import time

import curl_cffi.requests as cc
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yfinance as yf
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from _common import (
    CACHE,
    UNIVERSE_CSV,
    atomic_write_bytes,
    get_logger,
    today_et,
)

CHUNK_SIZE = 80
SLEEP_BETWEEN_CHUNKS_S = 2.0

log = get_logger("fetch_prices")


def pivot_to_long(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance returns wide multi-index columns (ticker, field) × date rows.
    Pivot to long format: one row per (ticker, date) with lowercase field cols.
    """
    if df.empty:
        return pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume"])
    # When yf.download is called with multiple tickers and group_by='ticker',
    # the columns are a MultiIndex of (ticker, field).
    if isinstance(df.columns, pd.MultiIndex):
        df = df.stack(level=0, future_stack=True)
        df.index.set_names(["date", "ticker"], inplace=True)
        df = df.reset_index()
    else:
        # Single ticker case (rare in batch mode but defensive)
        df = df.reset_index().rename(columns={"index": "date"})
        df["ticker"] = "UNKNOWN"
    df.columns = [c.lower() if isinstance(c, str) else c for c in df.columns]
    keep = ["ticker", "date", "open", "high", "low", "close", "volume"]
    df = df[[c for c in keep if c in df.columns]]
    df = df.dropna(subset=["close", "volume"])
    return df


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _download_chunk(tickers: list[str], session: cc.Session) -> pd.DataFrame:
    log.info("Downloading chunk of %d tickers", len(tickers))
    return yf.download(
        tickers,
        period="1y",
        interval="1d",
        group_by="ticker",
        threads=True,
        auto_adjust=True,
        session=session,
        progress=False,
    )


def download_universe(universe: list[str]) -> tuple[pd.DataFrame, list[str]]:
    session = cc.Session(impersonate="chrome")
    chunks = [universe[i : i + CHUNK_SIZE] for i in range(0, len(universe), CHUNK_SIZE)]
    frames: list[pd.DataFrame] = []
    failed: list[str] = []

    for i, chunk in enumerate(chunks):
        try:
            raw = _download_chunk(chunk, session)
            frames.append(pivot_to_long(raw))
        except (RetryError, Exception) as e:  # noqa: BLE001 — log and continue
            log.warning("Chunk %d failed after retries: %s", i, e)
            failed.extend(chunk)
        if i < len(chunks) - 1:
            time.sleep(SLEEP_BETWEEN_CHUNKS_S)

    if not frames:
        return pd.DataFrame(), failed

    df = pd.concat(frames, ignore_index=True)
    # Filter to tickers that actually produced data (yfinance silently
    # returns NaN columns for delisted/bad tickers).
    df = df.dropna(subset=["close"])
    found = set(df["ticker"].unique())
    failed.extend([t for t in universe if t not in found and t not in failed])
    return df, failed


def write_parquet_atomic(df: pd.DataFrame, path) -> str:
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
    parser.add_argument("--limit", type=int, default=None, help="Cap universe size (for testing)")
    args = parser.parse_args()

    if not UNIVERSE_CSV.exists():
        log.error("Universe file missing: %s. Run fetch_universe.py first.", UNIVERSE_CSV)
        return 2

    universe_df = pd.read_csv(UNIVERSE_CSV)
    tickers = universe_df["symbol"].tolist()
    if args.limit:
        tickers = tickers[: args.limit]

    log.info("Fetching prices for %d tickers", len(tickers))
    df, failed = download_universe(tickers)

    if df.empty:
        log.error("No data fetched. Failed: %d", len(failed))
        return 3

    out = CACHE / f"{today_et().isoformat()}.parquet"
    sha = write_parquet_atomic(df, out)
    log.info("Wrote %d rows to %s (sha256: %s, %d tickers failed)",
             len(df), out, sha[:12], len(failed))
    if failed:
        log.info("First 10 failed: %s", failed[:10])
    return 0


if __name__ == "__main__":
    sys.exit(main())
