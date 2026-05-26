"""Compute the two-bucket variation screen from the daily parquet cache.

Three variation definitions, OR-combined for inclusion:
  - Range:        max(High) - min(Low) over trailing 5 sessions
  - 5-day return: |Close[t] - Close[t-5]| (or pct equivalent for B)
  - Max daily:    max |daily Δclose| over trailing 5 sessions

Note: with auto_adjust=True (yfinance default), historical OHLC is
split-adjusted in-place. The dollar-change math |Close[t] - Close[t-5]|
reads as small after a split, which is correct — the security genuinely
didn't move in the split-adjusted frame. No special handling needed.

Uses session-index based slicing (groupby + tail of unique session
indices), not calendar rolling — this is correct in the presence of
holiday gaps in the trailing window.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

from _common import (
    AVG_VOLUME_WINDOW,
    CACHE,
    MIN_DOLLAR_VOLUME,
    PRICE_BAND_A,
    PRICE_BAND_B,
    RUNS,
    THRESHOLD_MAX_DAILY_A,
    THRESHOLD_MAX_DAILY_B,
    THRESHOLD_RANGE_A,
    THRESHOLD_RANGE_B,
    THRESHOLD_RET_5D_A,
    THRESHOLD_RET_5D_B,
    TRAILING_SESSIONS,
    UNIVERSE_CSV,
    ScreenRow,
    atomic_write_text,
    get_logger,
    today_et,
)

log = get_logger("compute_screens")
Q = Decimal("0.01")


def _to_decimal(x: float) -> Decimal:
    return Decimal(str(x)).quantize(Q, rounding=ROUND_HALF_UP)


def _last_n_sessions(df_ticker: pd.DataFrame, n: int) -> pd.DataFrame:
    return df_ticker.sort_values("date").tail(n)


def _avg_dollar_volume(df_ticker: pd.DataFrame, window: int) -> Decimal:
    last = df_ticker.sort_values("date").tail(window)
    if last.empty:
        return Decimal("0")
    dv = (last["close"] * last["volume"]).mean()
    return _to_decimal(float(dv))


def _compute_variations(df_ticker: pd.DataFrame, n: int) -> dict[str, Decimal] | None:
    last_n = _last_n_sessions(df_ticker, n)
    if len(last_n) < n:
        return None
    closes = last_n["close"].astype(float).tolist()
    highs = last_n["high"].astype(float).tolist()
    lows = last_n["low"].astype(float).tolist()
    range_dollar = max(highs) - min(lows)
    range_pct = (max(highs) / min(lows) - 1.0) if min(lows) > 0 else 0.0
    ret_5d_dollar = abs(closes[-1] - closes[0])
    ret_5d_pct = abs(closes[-1] / closes[0] - 1.0) if closes[0] > 0 else 0.0
    daily_dollar_moves = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    daily_pct_moves = [
        abs(closes[i] / closes[i - 1] - 1.0) if closes[i - 1] > 0 else 0.0
        for i in range(1, len(closes))
    ]
    return {
        "range_dollar": _to_decimal(range_dollar),
        "range_pct": _to_decimal(range_pct),
        "ret_5d_dollar": _to_decimal(ret_5d_dollar),
        "ret_5d_pct": _to_decimal(ret_5d_pct),
        "max_daily_dollar": _to_decimal(max(daily_dollar_moves) if daily_dollar_moves else 0.0),
        "max_daily_pct": _to_decimal(max(daily_pct_moves) if daily_pct_moves else 0.0),
        "last_close": _to_decimal(closes[-1]),
        "last_session_date": last_n["date"].max(),
    }


def _row_for_bucket_a(ticker: str, name: str, v: dict, dv: Decimal) -> ScreenRow | None:
    if not (PRICE_BAND_A[0] <= v["last_close"] <= PRICE_BAND_A[1]):
        return None
    if dv < MIN_DOLLAR_VOLUME:
        return None
    range_trig = v["range_dollar"] >= THRESHOLD_RANGE_A
    ret_trig = v["ret_5d_dollar"] >= THRESHOLD_RET_5D_A
    daily_trig = v["max_daily_dollar"] >= THRESHOLD_MAX_DAILY_A
    if not (range_trig or ret_trig or daily_trig):
        return None
    last_date = v["last_session_date"]
    if hasattr(last_date, "to_pydatetime"):
        last_date = last_date.to_pydatetime().date()
    return ScreenRow(
        ticker=ticker, bucket="A", name=name, sector=None,
        last_close=v["last_close"], avg_dollar_vol=dv,
        range_value=v["range_dollar"], range_triggers=range_trig,
        ret_5d_value=v["ret_5d_dollar"], ret_5d_triggers=ret_trig,
        max_daily_value=v["max_daily_dollar"], max_daily_triggers=daily_trig,
        last_session_date=last_date,
    )


def _row_for_bucket_b(ticker: str, name: str, v: dict, dv: Decimal) -> ScreenRow | None:
    if not (PRICE_BAND_B[0] <= v["last_close"] <= PRICE_BAND_B[1]):
        return None
    if dv < MIN_DOLLAR_VOLUME:
        return None
    range_trig = v["range_pct"] >= THRESHOLD_RANGE_B
    ret_trig = v["ret_5d_pct"] >= THRESHOLD_RET_5D_B
    daily_trig = v["max_daily_pct"] >= THRESHOLD_MAX_DAILY_B
    if not (range_trig or ret_trig or daily_trig):
        return None
    last_date = v["last_session_date"]
    if hasattr(last_date, "to_pydatetime"):
        last_date = last_date.to_pydatetime().date()
    return ScreenRow(
        ticker=ticker, bucket="B", name=name, sector=None,
        last_close=v["last_close"], avg_dollar_vol=dv,
        range_value=v["range_pct"], range_triggers=range_trig,
        ret_5d_value=v["ret_5d_pct"], ret_5d_triggers=ret_trig,
        max_daily_value=v["max_daily_pct"], max_daily_triggers=daily_trig,
        last_session_date=last_date,
    )


def compute_screens(ohlc: pd.DataFrame, universe: pd.DataFrame) -> list[ScreenRow]:
    name_map = dict(zip(universe["symbol"], universe["name"]))
    rows: list[ScreenRow] = []
    grouped = ohlc.groupby("ticker", sort=False)
    for ticker, df_ticker in grouped:
        v = _compute_variations(df_ticker, TRAILING_SESSIONS)
        if v is None:
            continue
        dv = _avg_dollar_volume(df_ticker, AVG_VOLUME_WINDOW)
        name = name_map.get(ticker, ticker)
        a = _row_for_bucket_a(ticker, name, v, dv)
        if a:
            rows.append(a)
        b = _row_for_bucket_b(ticker, name, v, dv)
        if b:
            rows.append(b)
    return rows


def _parquet_path() -> Path:
    return CACHE / f"{today_et().isoformat()}.parquet"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asof", type=str, default=None, help="Override date (ISO format)")
    args = parser.parse_args()

    asof: date = today_et() if args.asof is None else date.fromisoformat(args.asof)
    parquet_path = CACHE / f"{asof.isoformat()}.parquet"
    if not parquet_path.exists():
        log.error("OHLC cache missing: %s. Run fetch_prices.py first.", parquet_path)
        return 2

    if not UNIVERSE_CSV.exists():
        log.error("Universe missing: %s. Run fetch_universe.py first.", UNIVERSE_CSV)
        return 2

    ohlc = pd.read_parquet(parquet_path)
    ohlc["date"] = pd.to_datetime(ohlc["date"])
    universe = pd.read_csv(UNIVERSE_CSV)
    log.info("Computing screens on %d (ticker, date) rows, %d universe tickers",
             len(ohlc), len(universe))

    rows = compute_screens(ohlc, universe)
    log.info("Screen produced %d rows (A=%d, B=%d)",
             len(rows), sum(r.bucket == "A" for r in rows),
             sum(r.bucket == "B" for r in rows))

    RUNS.mkdir(parents=True, exist_ok=True)
    out = RUNS / f"{asof.isoformat()}.csv"
    parquet_sha = _file_sha256(parquet_path)

    if not rows:
        header = (
            f"# parquet_sha256={parquet_sha}\n"
            "ticker,bucket,name,sector,last_close,avg_dollar_vol,"
            "range_value,range_triggers,ret_5d_value,ret_5d_triggers,"
            "max_daily_value,max_daily_triggers,last_session_date\n"
        )
        atomic_write_text(out, header)
        log.warning("No rows passed screen; wrote header-only CSV to %s", out)
        return 0

    df = pd.DataFrame([r.model_dump() for r in rows])
    df = df.sort_values(["bucket", "ticker"]).reset_index(drop=True)
    csv_body = df.to_csv(index=False)
    payload = f"# parquet_sha256={parquet_sha}\n" + csv_body
    atomic_write_text(out, payload)
    log.info("Wrote %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
