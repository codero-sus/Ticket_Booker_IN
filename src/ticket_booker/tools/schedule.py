"""Train schedule / route scraper (BRUTE) via NTES + IRCTC fallback.

Strategy: NTES "Train Schedule" tab (text-driven) -> read halt table.
If NTES is down/captcha-hostile after retries, fall back to IRCTC train
search page and report whatever schedule info is visible. Auto-captcha runs
before every submit.
"""

from __future__ import annotations

import logging
import re

from ..utils import human_delay
from .base import BruteContext, ToolResult, run_with_browser

log = logging.getLogger("ticket_booker.tools.schedule")

NTES_URLS = (
    "https://enquiry.indianrail.gov.in/mntes/",
    "https://enquiry.indianrail.gov.in/ivrs",
)


def parse_schedule_tables(tables: list[list[list[str]]]) -> list[dict]:
    """Pick the table that looks like station halts. Never raises."""
    best: list[dict] = []
    for table in tables:
        try:
            rows: list[dict] = []
            for cells in table:
                joined = " | ".join(cells)
                # Halt rows usually contain a station code in brackets + times
                if re.search(r"\([A-Z]{2,5}\)", joined) and re.search(r"\d{1,2}:\d{2}", joined):
                    rows.append({"cells": cells, "text": " ".join(cells)})
            if len(rows) > len(best):
                best = rows
        except Exception:
            continue
    return best


def _via_ntes(ctx: BruteContext, train_no: str) -> dict:
    if not ctx.goto(*NTES_URLS):
        raise RuntimeError("NTES unreachable.")
    # Text-driven tab navigation (layout-proof)
    ctx.click_text("Train Schedule", "Schedule", "Time Table")
    human_delay(1.5, 3.0)
    ctx.solve_captchas_on_page()
    if not ctx.fill_near_text(("Train No", "Train Number", "Enter Train", "Train"), train_no):
        raise RuntimeError("Train-number box not found on NTES.")
    human_delay(0.5, 1.2)
    ctx.solve_captchas_on_page()
    if not ctx.click_text("Get Schedule", "Search", "Submit", "Show", "Go"):
        raise RuntimeError("Schedule submit button not found.")
    human_delay(2.0, 4.0)
    # Captcha re-ask loop (NTES loves captchas)
    for _ in range(2):
        if ctx.wait_text("Station", "Arrival", "Departure", "Source", "Destination",
                         "Invalid", "not found", timeout_s=18):
            break
        if ctx.solve_captchas_on_page():
            ctx.click_text("Get Schedule", "Search", "Submit", "Go")
            human_delay(2.0, 4.0)
    body = ctx.page_text()
    if re.search(r"invalid|not found|no record|no data", body, re.I) and "station" not in body.lower():
        raise ValueError(f"NTES has no schedule for train {train_no}.")
    halts = parse_schedule_tables(ctx.table_texts(max_tables=8))
    if not halts:
        # Fallback: mine station codes + times from raw text lines
        lines = []
        for ln in body.splitlines():
            if re.search(r"\([A-Z]{2,5}\)", ln) and re.search(r"\d{1,2}:\d{2}", ln):
                lines.append({"cells": [ln.strip()], "text": ln.strip()})
        halts = lines[:80]
    if not halts:
        ctx.shot("schedule_empty")
        raise RuntimeError("Schedule page unreadable (see screenshot).")
    return {"train_no": train_no, "halts": halts, "halt_count": len(halts), "via": "ntes"}


def _via_irctc(ctx: BruteContext, train_no: str) -> dict:
    from ..irctc.constants import HOME_URL

    if not ctx.goto(HOME_URL):
        raise RuntimeError("IRCTC unreachable for fallback.")
    ctx.ensure_login()
    # IRCTC train list sometimes has schedule links; brute-click any schedule text
    ctx.click_text("Train Schedule", "Schedule", "Time Table")
    human_delay(1.5, 3.0)
    halts = parse_schedule_tables(ctx.table_texts(max_tables=8))
    return {"train_no": train_no, "halts": halts, "halt_count": len(halts), "via": "irctc-fallback"}


def run_tool(cfg, train_no: str, headless: bool | None = None) -> ToolResult:
    train_no = (train_no or "").strip()
    if not re.fullmatch(r"\d{5}", train_no):
        return ToolResult(False, {}, f"Train number must be 5 digits, got {train_no!r}.")

    def _run(ctx: BruteContext) -> ToolResult:
        try:
            data = ctx.brute(lambda: _via_ntes(ctx, train_no), f"schedule {train_no}",
                             retries=3)
        except Exception as ntes_err:
            log.warning("NTES path failed (%s) — trying IRCTC fallback...", ntes_err)
            data = ctx.brute(lambda: _via_irctc(ctx, train_no), "schedule fallback",
                             retries=2)
            if not data["halts"]:
                raise RuntimeError(f"Both NTES and IRCTC failed. Last NTES error: {ntes_err}")
        first = data["halts"][0]["text"][:60] if data["halts"] else "?"
        last = data["halts"][-1]["text"][:60] if data["halts"] else "?"
        summary = f"Train {train_no}: {data['halt_count']} halts (via {data['via']})\n{first}\n...\n{last}"
        path = ctx.save_report(f"schedule_{train_no}", data, summary)
        return ToolResult(True, data, f"Train {train_no}: {data['halt_count']} halts.", str(path))

    try:
        return run_with_browser(cfg, headless, _run)
    except Exception as exc:
        log.error("Schedule tool failed: %s", exc)
        return ToolResult(False, {}, f"Schedule tool failed: {exc}")
