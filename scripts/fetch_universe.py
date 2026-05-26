"""Pull NYSE + NASDAQ listed common-stock universe from NASDAQ Trader."""
from __future__ import annotations

import argparse
import io
import sys

import pandas as pd
import requests

from _common import (
    UNIVERSE_CSV,
    TEST_UNIVERSE_50,
    atomic_write_text,
    get_logger,
)

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"

log = get_logger("fetch_universe")


def _fetch_pipe_separated(url: str) -> pd.DataFrame:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    text = resp.text
    # Last line is "File Creation Time" footer — drop it
    lines = [ln for ln in text.splitlines() if not ln.startswith("File Creation Time")]
    return pd.read_csv(io.StringIO("\n".join(lines)), sep="|")


def fetch_nasdaq_listed() -> pd.DataFrame:
    df = _fetch_pipe_separated(NASDAQ_LISTED_URL)
    df = df[df["Test Issue"] == "N"]
    df = df[df["ETF"] == "N"]
    df = df[df["Financial Status"] == "N"]
    return pd.DataFrame({
        "symbol": df["Symbol"],
        "name": df["Security Name"],
        "exchange": "NASDAQ",
    })


def fetch_other_listed() -> pd.DataFrame:
    df = _fetch_pipe_separated(OTHER_LISTED_URL)
    df = df[df["Test Issue"] == "N"]
    df = df[df["ETF"] == "N"]
    return pd.DataFrame({
        "symbol": df["ACT Symbol"],
        "name": df["Security Name"],
        "exchange": df["Exchange"].map({"A": "NYSE-MKT", "N": "NYSE", "P": "NYSE-ARCA"}).fillna("OTHER"),
    })


def _drop_special_chars(df: pd.DataFrame) -> pd.DataFrame:
    return df[~df["symbol"].str.contains(r"[=$.]", regex=True, na=False)]


def build_universe() -> pd.DataFrame:
    nasdaq = fetch_nasdaq_listed()
    other = fetch_other_listed()
    universe = pd.concat([nasdaq, other], ignore_index=True)
    universe = _drop_special_chars(universe)
    universe = universe.drop_duplicates(subset=["symbol"]).sort_values("symbol")
    universe = universe.reset_index(drop=True)
    return universe


def build_test_universe() -> pd.DataFrame:
    return pd.DataFrame({
        "symbol": TEST_UNIVERSE_50,
        "name": [f"{s} test" for s in TEST_UNIVERSE_50],
        "exchange": "TEST",
    })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Write a 50-ticker test universe instead of full NASDAQ/NYSE")
    args = parser.parse_args()

    if args.test:
        log.info("Building 50-ticker TEST universe")
        universe = build_test_universe()
    else:
        log.info("Fetching NASDAQ + NYSE common-stock universe")
        universe = build_universe()

    UNIVERSE_CSV.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(UNIVERSE_CSV, universe.to_csv(index=False))
    log.info("Wrote %d tickers to %s", len(universe), UNIVERSE_CSV)
    return 0


if __name__ == "__main__":
    sys.exit(main())
