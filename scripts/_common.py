from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal
import pandas as pd
from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"
CACHE = DATA / "cache"
RUNS = DATA / "runs"
UNIVERSE_CSV = DATA / "universe.csv"

ET = ZoneInfo("America/New_York")
NYSE = mcal.get_calendar("NYSE")

PRICE_BAND_A = (Decimal("300"), Decimal("800"))
PRICE_BAND_B = (Decimal("0.79"), Decimal("20"))

THRESHOLD_RANGE_A = Decimal("15")
THRESHOLD_RANGE_B = Decimal("0.20")
THRESHOLD_RET_5D_A = Decimal("15")
THRESHOLD_RET_5D_B = Decimal("0.20")
THRESHOLD_MAX_DAILY_A = Decimal("15")
THRESHOLD_MAX_DAILY_B = Decimal("0.20")

MIN_DOLLAR_VOLUME = Decimal("1000000")
TRAILING_SESSIONS = 5
AVG_VOLUME_WINDOW = 30


def today_et() -> date:
    return datetime.now(ET).date()


def last_trading_day(asof: date | None = None) -> date:
    asof = asof or today_et()
    schedule = NYSE.valid_days(start_date=asof - pd.Timedelta(days=14), end_date=asof)
    if len(schedule) == 0:
        raise RuntimeError(f"No trading days in 14 days before {asof}")
    return schedule[-1].date()


def is_trading_day(d: date | None = None) -> bool:
    d = d or today_et()
    valid = NYSE.valid_days(start_date=d, end_date=d)
    return len(valid) > 0


def get_logger(name: str) -> logging.Logger:
    log = logging.getLogger(name)
    if not log.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    return log


def atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def safe_resolve_under(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"{path} resolves outside {root}")
    return resolved


class ScreenRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    bucket: Literal["A", "B"]
    name: str
    sector: str | None
    last_close: Decimal
    avg_dollar_vol: Decimal
    range_value: Decimal
    range_triggers: bool
    ret_5d_value: Decimal
    ret_5d_triggers: bool
    max_daily_value: Decimal
    max_daily_triggers: bool
    last_session_date: date


TEST_UNIVERSE_50 = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "ORCL",
    "TSLA", "NFLX", "AMD", "PLTR", "COIN", "CRWD", "SMCI",
    "JPM", "GS", "MS", "C", "BAC",
    "BKNG", "MELI", "AZO", "NVR", "CMG", "FICO",
    "LLY", "UNH", "PFE", "MRNA", "JNJ",
    "COST", "WMT", "TGT", "HD", "LOW",
    "F", "GE", "T", "INTC", "WFC",
    "RIVN", "LCID", "NIO", "SOFI",
    "SAVA", "NVAX", "MARA", "RIOT", "PLUG",
]
