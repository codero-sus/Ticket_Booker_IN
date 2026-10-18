"""Seat/berth availability scraper (BRUTE): search -> read every train's status.

Reads TEXT (train numbers, class codes, AVAILABLE/RAC/WL counts) instead of
depending on IRCTC's grid DOM — layout changes can't kill it.
"""

from __future__ import annotations

import logging
import re

from ..config import Journey
from ..irctc.search import search_trains
from ..utils import human_delay
from .base import BruteContext, ToolResult, run_with_browser

log = logging.getLogger("ticket_booker.tools.availability")

TRAIN_NO_RE = re.compile(r"\b(\d{5})\b")
AVL_RE = re.compile(
    r"(1A|2A|3A|3E|CC|EC|EA|EV|VC|VS|SL|2S|FC)\b[^\n]{0,40}?"
    r"(AVAILABLE|AVL|RAC|WL|REGRET|NOT AVAILABLE)[^\d]{0,6}(\d{1,4})?",
    re.IGNORECASE,
)


def parse_train_rows(row_texts: list[str], class_code: str = "") -> list[dict]:
    """Parse train rows from raw text. Never raises; skips unreadable rows."""
    out: list[dict] = []
    for raw in row_texts:
        try:
            text = " ".join((raw or "").split())
            m = TRAIN_NO_RE.search(text)
            if not m:
                continue
            entry: dict = {"train_no": m.group(1), "classes": {}}
            for cls, status, count in AVL_RE.findall(text):
                cls = cls.upper()
                status = status.upper().replace("NOT AVAILABLE", "REGRET")
                if status == "AVL":
                    status = "AVAILABLE"
                entry["classes"][cls] = {
                    "status": status,
                    "count": int(count) if count and count.isdigit() else None,
                }
            if class_code and class_code.upper() not in entry["classes"]:
                entry["note"] = f"{class_code} not shown in row text"
            out.append(entry)
        except Exception as exc:
            log.debug("row parse skipped: %s", exc)
    return out


def _collect(ctx: BruteContext, journey: Journey) -> dict:
    from ..irctc.constants import HOME_URL

    if not ctx.goto(HOME_URL):
        raise RuntimeError("Could not open IRCTC.")
    ctx.ensure_login()
    ctx.brute(lambda: search_trains(ctx.page, journey), "train search", retries=2,
              reload_between=True)
    human_delay(2.5, 5.0)

    # Collect row texts — try several row shapes, keep whatever has a train no.
    row_texts: list[str] = []
    for sel in ("div.train-list", ".train-list", "app-train-list", "table tr", "li"):
        try:
            loc = ctx.page.locator(sel)
            n = loc.count()
            for i in range(min(n, 40)):
                try:
                    t = loc.nth(i).inner_text(timeout=2000) or ""
                    if TRAIN_NO_RE.search(t) and t not in row_texts:
                        row_texts.append(t)
                except Exception:
                    continue
            if row_texts:
                break
        except Exception:
            continue
    if not row_texts:
        # Last resort: whole page text, split by train numbers
        body = ctx.page_text()
        chunks = re.split(r"(?=\b\d{5}\b)", body)
        row_texts = [c[:1500] for c in chunks if TRAIN_NO_RE.search(c[:10])]
    if not row_texts:
        ctx.shot("availability_empty")
        raise RuntimeError("No trains found in results (see screenshot).")

    trains = parse_train_rows(row_texts, journey.class_code)
    if journey.train_no:
        trains = [t for t in trains if t["train_no"] == journey.train_no]
    return {
        "from": journey.from_station, "to": journey.to_station, "date": journey.date,
        "quota": journey.quota, "class_filter": journey.class_code,
        "trains": trains, "rows_scanned": len(row_texts),
    }


def run_tool(cfg, journey: Journey | None = None, headless: bool | None = None,
             train_no: str = "") -> ToolResult:
    journey = journey or cfg.journey
    if train_no.strip():
        journey = journey.model_copy(update={"train_no": train_no.strip()})

    def _run(ctx: BruteContext) -> ToolResult:
        data = ctx.brute(lambda: _collect(ctx, journey),
                         f"availability {journey.from_station}-{journey.to_station}",
                         retries=3, relogin_once=True)
        lines = [f"{journey.from_station}->{journey.to_station} {journey.date} [{journey.quota}]"]
        for t in data["trains"]:
            cls = data.get("class_filter", "")
            c = t["classes"].get(cls.upper(), {})
            if c:
                lines.append(f"  {t['train_no']} {cls}: {c['status']} {c.get('count') or ''}".rstrip())
            else:
                avail = ", ".join(f"{k}:{v['status']}{v.get('count') or ''}" for k, v in t["classes"].items())
                lines.append(f"  {t['train_no']}: {avail or 'unreadable'}")
        path = ctx.save_report(f"availability_{journey.from_station}_{journey.to_station}", data, "\n".join(lines))
        return ToolResult(True, data, f"{len(data['trains'])} train(s) scanned.", str(path))

    try:
        return run_with_browser(cfg, headless, _run)
    except Exception as exc:
        log.error("Availability tool failed: %s", exc)
        return ToolResult(False, {}, f"Availability tool failed: {exc}")
