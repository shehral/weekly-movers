---
status: pending
priority: p2
issue_id: "003"
tags: [code-review, python, idioms, type-safety]
dependencies: []
---

# Adopt Python idioms: tenacity, Pydantic + Decimal, NewType("SafeHtml")

## Problem Statement

The plan's Python code snippets (Phase 1 yfinance retry loop, Phase 4
bleach + Jinja2 setup, planned `fetch_prices.py` + `generate_narrative.py`)
are functionally correct but not idiomatic 2026 Python. Specifically:

1. The yfinance snippet uses `yf.config.network.retries = 3` + a manual
   `try/except + time.sleep` loop. The 2026 standard is `tenacity` with
   typed exponential backoff and jittered retry.
2. The run-CSV schema (13 fields, written/read by 4 scripts) has no
   validating dataclass. Prices use `float` instead of `Decimal`.
3. The bleach+Jinja pipeline has no compile-time enforcement that
   only-sanitized HTML reaches the template. `| safe` filter abuse is
   the standard XSS bug source.

## Findings

- **Source:** kieran-python-reviewer.
- These aren't theoretical — `float` for stock prices accumulates IEEE-754
  errors that show up as `$199.99999999` in rendered output; the manual
  retry loop has no jitter and won't survive Yahoo's burst rate-limiting;
  the lack of a `SafeHtml` type means a future hand-edit could
  accidentally pipe raw LLM output to the template.

## Proposed Solutions

### Sub-finding A: Use tenacity for yfinance retries

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type(yf.exceptions.YFRateLimitError),
)
def _download_chunk(tickers, session):
    return yf.download(list(tickers), period="1y", interval="1d",
                       group_by="ticker", threads=True,
                       auto_adjust=True, session=session, progress=False)
```

Drop `yf.config.network.retries = 3` (it does less and is less testable).

### Sub-finding B: Pydantic model with `Decimal` for the run-CSV row

```python
from decimal import Decimal
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict

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
```

Then `pd.DataFrame([row.model_dump() for row in rows])`. Mypy --strict
catches typos at compile time.

### Sub-finding C: `NewType("SafeHtml")` enforces bleach-before-render

```python
from typing import NewType
SafeHtml = NewType("SafeHtml", str)

def sanitize_llm_markdown(raw: str) -> SafeHtml:
    md_html = markdown_it.MarkdownIt().render(raw)
    return SafeHtml(bleach.clean(md_html, tags=ALLOWED_TAGS,
                                  attributes=ALLOWED_ATTRS,
                                  protocols=frozenset({"https"}),
                                  strip=True))

def render(narrative: SafeHtml, date: date) -> None: ...
```

`render()` won't compile if someone passes a raw `str`. Defense in
depth on top of Jinja `autoescape`.

### Sub-finding D: pandas rolling API for trailing-5d (not hand-slicing)

`df.groupby('ticker').tail(5)` silently breaks if a ticker has gaps
(holiday in the window). Use:

```python
last5 = df.set_index("date").groupby("ticker", group_keys=False).tail(5)
range_val = last5.groupby("ticker").agg(hi=("high", "max"),
                                         lo=("low", "min"))
range_val["range"] = range_val["hi"] - range_val["lo"]
```

Or `df.groupby("ticker").rolling("5D", on="date").agg(...)`.

## Recommended Action

(Filled during /ce:work — likely all four sub-findings, plus add
`tenacity` and `pydantic` to requirements.txt.)

## Technical Details

**New dependencies:** `tenacity`, `pydantic` (likely already a transitive)

**Affected files:** `scripts/fetch_prices.py`, `scripts/compute_screens.py`,
`scripts/generate_narrative.py`, plan snippets in Phase 1 + Phase 4
Research Insights.

## Acceptance Criteria

- [ ] No manual retry loops; all yfinance calls wrapped in tenacity
      decorators
- [ ] `mypy --strict` passes on every script
- [ ] `Decimal` used for `last_close`, all `*_value` columns,
      `avg_dollar_vol`. NOT `float`.
- [ ] `SafeHtml` NewType used end-to-end in narrative pipeline
- [ ] No `df.groupby(...).tail(5)` for the variation metrics; either
      session-index based slicing OR pandas rolling API

## Work Log

(empty)

## Resources

- tenacity: https://tenacity.readthedocs.io/
- Pydantic v2: https://docs.pydantic.dev/latest/
- Python typing.NewType: https://docs.python.org/3/library/typing.html#typing.NewType
- bleach: https://bleach.readthedocs.io/
