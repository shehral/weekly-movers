"""Generate a daily ~200-word LLM narrative about the screen output.

Two sections: "Notable today" + "What changed vs yesterday" (diff sets).

Security posture:
- Freshness gate: refuses to run if run_csv.last_session_date doesn't
  match today's ET trading day. Prevents publishing a stale narrative.
- Prompt-injection defense: strips non-ASCII from ticker names + caps
  field lengths before constructing the prompt. Yahoo / NASDAQ Trader
  feeds names verbatim; adversarial content is unlikely but cheap to
  defend against.
- XSS hardening on LLM output:
  - Markdown-it-py for raw → HTML
  - bleach with a strict allowlist (no <script>, no inline events,
    only https:// hrefs)
  - Jinja2 autoescape=select_autoescape enabled at Environment level
  - CSP meta tag in the template
- Idempotency: if docs/notes/<DATE>.html exists and --force not passed,
  skip (don't overwrite a published narrative with a non-deterministic
  resample).
- Atomic file writes via tmp + os.replace.
- Fail-closed if ANTHROPIC_API_KEY env var is unset.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import NewType

import bleach
import markdown_it
import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from _common import (
    DOCS,
    NYSE,
    ROOT,
    RUNS,
    atomic_write_text,
    get_logger,
    today_et,
)

log = get_logger("narrative")
TEMPLATES = ROOT / "templates"

env = Environment(
    loader=FileSystemLoader(str(TEMPLATES)),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

ALLOWED_TAGS = frozenset({"p", "strong", "em", "ul", "ol", "li", "code", "a", "br", "h3"})
ALLOWED_ATTRS = {"a": ["href"]}
MAX_FIELD_LEN = 80
ASCII_ONLY = re.compile(r"[^\x20-\x7e\n]")

SafeHtml = NewType("SafeHtml", str)


class FreshnessError(RuntimeError):
    pass


class NarrativeError(RuntimeError):
    pass


def _sanitize_field(s: str) -> str:
    s = ASCII_ONLY.sub("", str(s))
    return s[:MAX_FIELD_LEN]


def _read_run(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, comment="#")
    for col in ("range_triggers", "ret_5d_triggers", "max_daily_triggers"):
        df[col] = df[col].astype(str).str.lower() == "true"
    return df


def _trading_day_offset(d: date, days_back: int = 1) -> date:
    schedule = NYSE.valid_days(start_date=d - timedelta(days=days_back * 5),
                                end_date=d)
    valid = [s.date() for s in schedule if s.date() < d]
    if not valid:
        raise NarrativeError(f"No trading day before {d}")
    return valid[-days_back] if len(valid) >= days_back else valid[-1]


def _load_run_pair(asof: date) -> tuple[pd.DataFrame, pd.DataFrame | None, date | None]:
    today_path = RUNS / f"{asof.isoformat()}.csv"
    if not today_path.exists():
        raise NarrativeError(f"Today's run CSV missing: {today_path}")
    today_df = _read_run(today_path)

    yesterday: date | None = None
    yesterday_df: pd.DataFrame | None = None
    for candidate_days_back in range(1, 7):
        try:
            cand = _trading_day_offset(asof, candidate_days_back)
        except NarrativeError:
            break
        cand_path = RUNS / f"{cand.isoformat()}.csv"
        if cand_path.exists():
            yesterday_df = _read_run(cand_path)
            yesterday = cand
            break
    return today_df, yesterday_df, yesterday


def _freshness_gate(today_df: pd.DataFrame, asof: date, max_stale_sessions: int = 2) -> None:
    """Refuse to run if the screen is more than `max_stale_sessions` trading
    days behind the most-recent expected session.

    Expected session = today if today is a trading day, else the most recent
    prior trading day. The gate allows up to `max_stale_sessions` of slip to
    accommodate upstream provider rate-limit edge cases (e.g., Polygon
    free-tier 429 on the final daily call burns one trading day's data).
    """
    last = pd.to_datetime(today_df["last_session_date"]).max().date()
    if NYSE.valid_days(start_date=asof, end_date=asof).size > 0:
        expected = asof
    else:
        expected = _trading_day_offset(asof, 1)

    schedule = NYSE.valid_days(start_date=last, end_date=expected)
    sessions_behind = max(0, len(schedule) - 1)
    if sessions_behind == 0:
        return
    if sessions_behind <= max_stale_sessions:
        log.warning(
            "Screen is %d trading sessions stale (last=%s, expected=%s) — proceeding.",
            sessions_behind, last, expected,
        )
        return
    raise FreshnessError(
        f"Freshness gate: screen is {sessions_behind} trading sessions stale "
        f"(last={last}, expected={expected}, max_stale_sessions={max_stale_sessions}). "
        "Pipeline 1 may not have refreshed in days. Aborting."
    )


def _compute_diff(today: pd.DataFrame, yesterday: pd.DataFrame | None) -> dict:
    today_tickers = set(today["ticker"])
    if yesterday is None:
        return {"new_today": [], "dropped_today": [], "persistent": list(today_tickers)}
    y = set(yesterday["ticker"])
    return {
        "new_today": sorted(today_tickers - y),
        "dropped_today": sorted(y - today_tickers),
        "persistent": sorted(today_tickers & y),
    }


def _top_movers(df: pd.DataFrame, metric: str, n: int = 5) -> list[dict]:
    sub = df.nlargest(n, metric)
    return [
        {
            "ticker": _sanitize_field(r["ticker"]),
            "name": _sanitize_field(r["name"]),
            "value": float(r[metric]),
            "bucket": r["bucket"],
        }
        for _, r in sub.iterrows()
    ]


def _build_prompt(today: pd.DataFrame, diff: dict, yesterday_date: date | None, asof: date) -> str:
    a = today[today["bucket"] == "A"]
    b = today[today["bucket"] == "B"]

    context = {
        "as_of": asof.isoformat(),
        "yesterday_date": yesterday_date.isoformat() if yesterday_date else None,
        "bucket_a_count": len(a),
        "bucket_b_count": len(b),
        "bucket_a_top_range": _top_movers(a, "range_value", 5),
        "bucket_a_top_ret": _top_movers(a, "ret_5d_value", 5),
        "bucket_a_top_daily": _top_movers(a, "max_daily_value", 5),
        "bucket_b_top_range": _top_movers(b, "range_value", 5),
        "bucket_b_top_ret": _top_movers(b, "ret_5d_value", 5),
        "bucket_b_top_daily": _top_movers(b, "max_daily_value", 5),
        "new_today": [_sanitize_field(t) for t in diff["new_today"][:15]],
        "dropped_today": [_sanitize_field(t) for t in diff["dropped_today"][:15]],
        "new_today_count": len(diff["new_today"]),
        "dropped_today_count": len(diff["dropped_today"]),
    }

    has_diff = yesterday_date is not None

    return f"""You write the daily companion note for a public US-equity volatility
screener called Weekly Movers. The screener runs each US trading day morning and
publishes two buckets: mid-priced movers ($300-$800 with $15+ weekly variation)
and penny movers ($0.79-$20 with 20%+ weekly variation).

Today is {context['as_of']}. Today's screen produced {context['bucket_a_count']} Bucket A names and {context['bucket_b_count']} Bucket B names.

TODAY'S TOP MOVERS (JSON):
{json.dumps(context, indent=2, default=str)}

Write a note in TWO sections, ~200 words total, in plain markdown. Tone: indie
research note — observational, specific, not breathless. No financial advice.
No predictions.

Section 1 — "Notable today" (~120 words):
- Pick 3-5 names from across both buckets that stand out. Names that triggered
  ALL THREE variation definitions are particularly noteworthy. Reference each
  by ticker.
- Mention the dominant flavor: is today's list heavy with one sector or theme
  (semis, biotech, crypto-related, etc.)?
- Use concrete numbers ("AMD's $88 weekly range").

Section 2 — "What changed vs {context['yesterday_date'] or 'yesterday'}" (~80 words):
{'- Compare to yesterday: ' + str(context['new_today_count']) + ' names joined, ' + str(context['dropped_today_count']) + ' dropped.' if has_diff else '- (No prior trading day to diff against; skip this section.)'}
- Name a few persistent / new / dropped tickers if they're notable.

Constraints:
- Use only the data provided above. Do not invent names, prices, or events.
- Tickers as `<code>AAPL</code>` markdown.
- No <script>, no inline event handlers, no images, no external scripts.
- Two `### ` markdown headers: "Notable today" and "What changed".
- One blank line between sections.
"""


def _call_claude(prompt: str) -> str:
    from anthropic import Anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise NarrativeError(
            "ANTHROPIC_API_KEY env var unset. Set it (or source ~/.weekly-movers-env) before running."
        )
    client = Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    return "\n".join(parts).strip()


def _sanitize_llm_markdown(raw: str) -> SafeHtml:
    md_html = markdown_it.MarkdownIt().render(raw)
    clean = bleach.clean(
        md_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=frozenset({"https"}),
        strip=True,
    )
    return SafeHtml(clean)


def _write_note(html: SafeHtml, asof: date, yesterday: date | None, today_df: pd.DataFrame) -> Path:
    template = env.get_template("notes.html.j2")
    rendered = template.render(
        as_of=asof.isoformat(),
        yesterday_date=yesterday.isoformat() if yesterday else None,
        narrative=html,
        screen_size=len(today_df),
        universe_size="6,500+",
        asset_root="..",
    )
    notes_dir = DOCS / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    out = notes_dir / f"{asof.isoformat()}.html"
    atomic_write_text(out, rendered)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asof", type=str, default=None)
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing note instead of skipping.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the prompt instead of calling Claude.")
    args = parser.parse_args()

    asof = today_et() if args.asof is None else date.fromisoformat(args.asof)
    note_path = DOCS / "notes" / f"{asof.isoformat()}.html"
    if note_path.exists() and not args.force:
        log.info("Note already exists: %s — skipping (use --force to overwrite)", note_path)
        return 0

    today_df, yesterday_df, yesterday_date = _load_run_pair(asof)
    _freshness_gate(today_df, asof)
    log.info("Loaded today: %d rows; yesterday (%s): %s rows",
             len(today_df),
             yesterday_date,
             len(yesterday_df) if yesterday_df is not None else "none")

    diff = _compute_diff(today_df, yesterday_df)
    log.info("Diff: %d new, %d dropped, %d persistent",
             len(diff["new_today"]), len(diff["dropped_today"]), len(diff["persistent"]))

    prompt = _build_prompt(today_df, diff, yesterday_date, asof)
    if args.dry_run:
        print(prompt)
        return 0

    raw = _call_claude(prompt)
    log.info("Claude returned %d chars", len(raw))
    html = _sanitize_llm_markdown(raw)
    out = _write_note(html, asof, yesterday_date, today_df)
    log.info("Wrote %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
