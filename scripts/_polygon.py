"""Polygon.io adapter — Grouped Daily Bars endpoint.

One API call returns OHLC for *every* US stock for a single trading day.
30 calls covers our 30-day avg-volume + 5-session variation screen for
the full universe.

Free tier limit: 5 calls/min. Sleep 12.5s between calls to stay under.
"""
from __future__ import annotations

import os
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from _common import get_logger

GROUPED_URL = "https://api.polygon.io/v2/aggs/grouped/locale/us/market/stocks/{date}"
SLEEP_BETWEEN_CALLS_S = 12.5  # free tier: 5 calls/min
TIMEOUT_S = 30

log = get_logger("polygon")


class PolygonError(RuntimeError):
    pass


class PolygonRateLimitError(PolygonError):
    pass


def _load_env_file(path: Path = Path.home() / ".weekly-movers-env") -> None:
    if "POLYGON_API_KEY" in os.environ:
        return
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip("'\"")
        os.environ.setdefault(k.strip(), v)


def get_api_key() -> str:
    _load_env_file()
    key = os.environ.get("POLYGON_API_KEY")
    if not key:
        raise PolygonError(
            "POLYGON_API_KEY env var unset. Get a free key at https://polygon.io/ "
            "and `export POLYGON_API_KEY=<key>` (or save to ~/.weekly-movers-env)."
        )
    return key


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    retry=retry_if_exception_type((PolygonRateLimitError, requests.RequestException)),
    reraise=True,
)
def _request_one_day(d: date, api_key: str, session: requests.Session) -> dict:
    url = GROUPED_URL.format(date=d.isoformat())
    r = session.get(url, params={"apiKey": api_key, "adjusted": "true"}, timeout=TIMEOUT_S)
    if r.status_code == 429:
        raise PolygonRateLimitError(f"429 on {d}")
    r.raise_for_status()
    data = r.json()
    if data.get("status") not in ("OK", "DELAYED"):
        raise PolygonError(f"Bad status for {d}: {data.get('status')} — {data.get('error', '')}")
    return data


def fetch_grouped_daily(d: date, api_key: str, session: requests.Session | None = None) -> pd.DataFrame:
    """Fetch OHLC for all US stocks on a single trading day.

    Returns long-format DataFrame: ticker, date, open, high, low, close, volume.
    """
    session = session or requests.Session()
    data = _request_one_day(d, api_key, session)
    results = data.get("results", [])
    if not results:
        log.warning("No results for %s", d)
        return pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(results)
    df = df.rename(columns={"T": "ticker", "o": "open", "h": "high",
                            "l": "low", "c": "close", "v": "volume"})
    df["date"] = pd.Timestamp(d)
    return df[["ticker", "date", "open", "high", "low", "close", "volume"]]


def fetch_many_days(days: list[date], api_key: str | None = None) -> pd.DataFrame:
    """Fetch grouped daily bars for multiple trading days, rate-limited.

    For each day, one API call. Sleep 12.5s between calls to stay under
    the free-tier 5-calls/min limit.
    """
    api_key = api_key or get_api_key()
    session = requests.Session()
    frames: list[pd.DataFrame] = []
    for i, d in enumerate(days):
        log.info("Polygon: fetching %s (%d/%d)", d, i + 1, len(days))
        try:
            df = fetch_grouped_daily(d, api_key, session)
            if not df.empty:
                frames.append(df)
        except PolygonError as e:
            log.warning("Polygon failed for %s: %s", d, e)
        if i < len(days) - 1:
            time.sleep(SLEEP_BETWEEN_CALLS_S)
    if not frames:
        return pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume"])
    return pd.concat(frames, ignore_index=True)
