"""Fetch 252-day daily history for the tickers in today's screen.

Uses yfinance batch download. ~500-600 tickers is well under Yahoo's
per-IP rate-limit wall (~1,300 ticker requests), so batch downloads
work reliably at this scale.

Output: data/cache/chart_history_<DATE>.parquet (gitignored).
"""
from __future__ import annotations

import argparse
import io
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yfinance as yf
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from _common import CACHE, RUNS, atomic_write_bytes, get_logger, today_et

CHUNK_SIZE = 80
SLEEP_BETWEEN_CHUNKS_S = 2.0

log = get_logger("fetch_chart_history")


def _read_run_tickers(run_csv: Path) -> list[str]:
    df = pd.read_csv(run_csv, comment="#")
    return sorted(df["ticker"].unique().tolist())


def _pivot_to_long(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume"])
    if isinstance(df.columns, pd.MultiIndex):
        df = df.stack(level=0, future_stack=True)
        df.index.set_names(["date", "ticker"], inplace=True)
        df = df.reset_index()
    else:
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
def _download_chunk(tickers: list[str]) -> pd.DataFrame:
    return yf.download(
        tickers,
        period="1y",
        interval="1d",
        group_by="ticker",
        threads=True,
        auto_adjust=True,
        progress=False,
    )


def fetch_chart_history(tickers: list[str]) -> tuple[pd.DataFrame, list[str]]:
    chunks = [tickers[i : i + CHUNK_SIZE] for i in range(0, len(tickers), CHUNK_SIZE)]
    frames: list[pd.DataFrame] = []
    failed: list[str] = []
    for i, chunk in enumerate(chunks):
        log.info("Chart history chunk %d/%d (%d tickers)", i + 1, len(chunks), len(chunk))
        try:
            raw = _download_chunk(chunk)
            frames.append(_pivot_to_long(raw))
        except Exception as e:  # noqa: BLE001
            log.warning("Chunk failed after retries: %s", e)
            failed.extend(chunk)
        if i < len(chunks) - 1:
            time.sleep(SLEEP_BETWEEN_CHUNKS_S)

    if not frames:
        return pd.DataFrame(), failed

    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["close"])
    found = set(df["ticker"].unique())
    failed.extend([t for t in tickers if t not in found and t not in failed])
    return df, failed


def write_parquet_atomic(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, buf, compression="zstd")
    atomic_write_bytes(path, buf.getvalue())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asof", type=str, default=None)
    args = parser.parse_args()

    asof: date = today_et() if args.asof is None else date.fromisoformat(args.asof)
    run_csv = RUNS / f"{asof.isoformat()}.csv"
    if not run_csv.exists():
        log.error("Run CSV missing: %s. Run compute_screens.py first.", run_csv)
        return 2

    tickers = _read_run_tickers(run_csv)
    log.info("Fetching 1y history for %d screened tickers", len(tickers))

    df, failed = fetch_chart_history(tickers)
    if df.empty:
        log.error("No history fetched; %d tickers failed", len(failed))
        return 3

    out = CACHE / f"chart_history_{asof.isoformat()}.parquet"
    write_parquet_atomic(df, out)
    log.info("Wrote %d rows for %d tickers to %s (%d failed)",
             len(df), df["ticker"].nunique(), out, len(failed))
    if failed:
        log.info("First 10 failed: %s", failed[:10])
    return 0


if __name__ == "__main__":
    sys.exit(main())
