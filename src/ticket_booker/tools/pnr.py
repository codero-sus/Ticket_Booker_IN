"""PNR status scraper (BRUTE): login -> PNR enquiry -> parse passengers/chart.

Pure parser `parse_pnr_body()` is unit-tested offline; the browser flow only
collects raw text/tables and feeds the parser (so DOM changes rarely break
extraction — we read TEXT, not divs).
"""

from __future__ import annotations

import logging
import re

from ..utils import human_delay
from .base import BruteContext, ToolResult, run_with_browser

log = logging.getLogger("ticket_booker.tools.pnr")

PNR_URLS = (
    "https://www.irctc.co.in/nget/pnr-status",
    "https://www.irctc.co.in/nget/train-search",  # fallback: navigate via menu text
)

STATUS_RE = re.compile(r"\b(CNF|RAC\s?\d*|WL\s?\d*|CAN|NOSB|WEBCAN|CANCELLED)\b", re.IGNORECASE)
PNR_RE = re.compile(r"\b(\d{10})\b")


def parse_pnr_body(text: str) -> dict:
    """Best-effort parse of PNR enquiry page text. Never raises."""
    out: dict = {"pnr": None, "chart_status": None, "statuses": [], "raw_lines": []}
    try:
        text = text or ""
        m = PNR_RE.search(text)
        if m:
            out["pnr"] = m.group(1)
        low = text.lower()
        if "chart" in low:
            if "not prepared" in low:
                out["chart_status"] = "NOT PREPARED"
            elif "prepared" in low:
                out["chart_status"] = "PREPARED"
        out["statuses"] = sorted({s.upper().replace(" ", "") for s in STATUS_RE.findall(text)})
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        # Keep lines that look like passenger/status info
        keep = [ln for ln in lines if STATUS_RE.search(ln) or re.search(r"\b(passenger|coach|berth|seat|fare|train|date|from|to)\b", ln, re.I)]
        out["raw_lines"] = keep[:40]
    except Exception as exc:  # parser must never kill the tool
        log.debug("parse_pnr_body degraded: %s", exc)
    return out


def _collect(ctx: BruteContext, pnr: str) -> dict:
    if not ctx.goto(*PNR_URLS):
        raise RuntimeError("Could not open IRCTC PNR page.")
    # Maybe we landed on train-search fallback -> click PNR STATUS menu text
    if not ctx.has_text("PNR", "pnr enquiry", "pnr status"):
        ctx.click_text("PNR Status", "PNR STATUS", "PNR Enquiry")
        human_delay(1.5, 3.0)

    ctx.ensure_login()
    ctx.solve_captchas_on_page()

    if not ctx.fill_near_text(("PNR Number", "PNR No", "Enter PNR", "PNR"), pnr):
        raise RuntimeError("PNR input box not found.")
    human_delay(0.5, 1.2)
    ctx.solve_captchas_on_page()
    if not ctx.click_text("Submit", "Get Status", "Search", "Check Status", verify_change=True):
        raise RuntimeError("Submit button not found.")
    human_delay(2.0, 4.0)

    # Captcha wrong? IRCTC re-asks — brute: solve again + resubmit, twice.
    for _ in range(2):
        hit = ctx.wait_text("Passenger", "Chart", "Booking Status", "Current Status",
                            "Invalid PNR", "PNR not", timeout_s=20)
        if hit and ("invalid" in hit.lower() or "not" in hit.lower()):
            raise ValueError(f"IRCTC says PNR {pnr} is invalid.")
        if hit:
            break
        if ctx.solve_captchas_on_page():
            ctx.click_text("Submit", "Get Status", "Search", verify_change=True)
            human_delay(2.0, 4.0)
        else:
            break

    body = ctx.page_text()
    data = parse_pnr_body(body)
    data["tables_found"] = len(ctx.table_texts())
    # Attach first table (usually the passenger grid) when present
    tables = ctx.table_texts(max_tables=2)
    if tables:
        data["passenger_table"] = tables[0][:12]
    if not data["statuses"] and not data.get("passenger_table"):
        ctx.shot("pnr_empty")
        raise RuntimeError("PNR page gave no readable status (see screenshot).")
    data["pnr"] = data["pnr"] or pnr
    return data


def run_tool(cfg, pnr: str, headless: bool | None = None) -> ToolResult:
    pnr = (pnr or "").strip()
    if not re.fullmatch(r"\d{10}", pnr):
        return ToolResult(False, {}, f"PNR must be 10 digits, got {pnr!r}.")

    def _run(ctx: BruteContext) -> ToolResult:
        data = ctx.brute(lambda: _collect(ctx, pnr), f"PNR {pnr}",
                         retries=3, relogin_once=True)
        summary = (
            f"PNR: {data.get('pnr')}\nChart: {data.get('chart_status') or 'unknown'}\n"
            f"Statuses seen: {', '.join(data.get('statuses', [])) or 'none'}\n"
        )
        path = ctx.save_report(f"pnr_{pnr}", data, summary)
        return ToolResult(True, data, f"PNR {pnr}: {', '.join(data.get('statuses', []))}", str(path))

    try:
        return run_with_browser(cfg, headless, _run)
    except Exception as exc:
        log.error("PNR tool failed BRUTALLY but finally: %s", exc)
        return ToolResult(False, {}, f"PNR tool failed: {exc}")
