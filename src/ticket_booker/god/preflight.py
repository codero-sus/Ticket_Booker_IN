"""Pre-flight checks — find booking-killers BEFORE 10 AM, not during.

`ticket-booker preflight -c config.json` verifies: date sanity, 60-day ARP
window, Tatkal window timing, stations, passenger limits, contact, payment
config, captcha solvers, browser binaries. FAIL = do not fly. WARN = flyable
but risky. Offline-safe and unit-tested.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field

log = logging.getLogger("ticket_booker.god.preflight")


@dataclass
class PreflightResult:
    ok: bool
    checks: list = field(default_factory=list)


def _c(name: str, ok: bool, msg: str, level: str = "fail") -> dict:
    return {"name": name, "ok": bool(ok), "msg": str(msg),
            "level": "ok" if ok else level}


def preflight(cfg, today=None) -> PreflightResult:
    from ..timing import format_duration, now_ist, parse_journey_date, tatkal_open_datetime
    from .algebra import is_void
    from .signals import title_for_level

    checks: list[dict] = []
    j = cfg.journey
    today = today or now_ist().date()

    try:
        jd = parse_journey_date(j.date)
    except Exception as exc:
        return PreflightResult(False, [_c("journey.date", False, str(exc))])
    days = (jd - today).days
    checks.append(_c("journey.date", days >= 0,
                     f"{jd} ({'PAST!' if days < 0 else f'{days}d ahead'})"))
    checks.append(_c("arp.window", 0 <= days <= 60,
                     f"{days}d ahead (ARP limit 60d)" if days >= 0 else "past date"))

    if j.quota in ("TQ", "PT"):
        op = tatkal_open_datetime(jd, j.class_code)
        now = now_ist()
        if now > op:
            ago = (now - op).total_seconds()
            checks.append(_c("tatkal.window", False,
                             f"opened {format_duration(ago)} ago — leftovers only",
                             level="warn"))
        else:
            left = (op - now).total_seconds()
            msg = f"opens in {format_duration(left)}"
            checks.append(_c("tatkal.window", True, msg + (" — GET READY" if left < 6 * 3600 else "")))
    else:
        checks.append(_c("tatkal.window", True, f"quota {j.quota} (no window)"))

    checks.append(_c("stations", j.from_station != j.to_station,
                     f"{j.from_station}->{j.to_station}"))
    npax = len(cfg.passengers)
    if j.quota == "TQ" and npax > 4:
        checks.append(_c("passengers.count", False, f"{npax} pax but Tatkal max is 4/PNR"))
    else:
        checks.append(_c("passengers.count", npax <= 6, f"{npax} pax"))

    mob = (cfg.preferences.mobile or cfg.irctc.mobile or "").strip()
    checks.append(_c("contact.mobile", len(mob) == 10 and mob.isdigit(),
                     mob or "missing — form fill may stall", level="warn"))
    if cfg.payment.method == "upi" and not (cfg.payment.upi_id or "").strip():
        checks.append(_c("payment.upi", False, "method=upi but upi_id empty", level="warn"))
    else:
        checks.append(_c("payment.upi", True, cfg.payment.method))

    if cfg.captcha.mode == "manual":
        checks.append(_c("captcha.solvers", True, "manual mode (you solve)"))
    else:
        ocr_ok = cfg.captcha.ocr.enabled and bool(shutil.which("tesseract"))
        svc_ok = cfg.captcha.service.enabled and bool((cfg.captcha.service.api_key or "").strip())
        gem_cfg = getattr(cfg.captcha, "gemini", None)
        gem_key = bool(((getattr(gem_cfg, "api_key", "") or "").strip()))
        gem_on = bool(getattr(gem_cfg, "enabled", False))
        gem_ok = gem_on and (gem_key or getattr(gem_cfg, "mode", "auto") in ("auto", "nano"))
        if gem_ok:
            gem_txt = "api+nano" if gem_key else "nano (in-browser)"
        else:
            gem_txt = "off"
        checks.append(_c("captcha.solvers", bool(ocr_ok or svc_ok or gem_ok),
                         f"gemini={gem_txt}, ocr={'yes' if ocr_ok else 'no'}, "
                         f"service={'yes' if svc_ok else 'no'}",
                         level="warn"))

    # Buster bridge: icon -> PLAY. Missing .xpi is fine (native path still works).
    b_cfg = getattr(cfg.captcha, "buster", None)
    if b_cfg is not None and getattr(b_cfg, "enabled", False):
        from pathlib import Path as _P

        _xpi = _P(getattr(b_cfg, "extension_path", "") or "")
        _has_xpi = bool(str(_xpi) and _xpi.exists())
        _mode = getattr(b_cfg, "mode", "auto")
        if _has_xpi:
            checks.append(_c("captcha.buster", True,
                             f"extension loaded ({_xpi.name}), mode={_mode}: "
                             "icon #solver-button -> PLAY"))
        elif _mode == "extension":
            checks.append(_c("captcha.buster", False,
                             f"mode=extension but {_xpi} is missing - run "
                             "`ticket-booker buster --install`"))
        else:
            checks.append(_c("captcha.buster", True,
                             f"mode={_mode}: native icon->PLAY path (no .xpi; "
                             "`ticket-booker buster --install` for the real one)",
                             level="warn"))

    arm_at = str(getattr(getattr(cfg, "brute", None), "arm_at", "") or "").strip()
    if arm_at:
        try:
            from .chronos import parse_hhmm

            h, m, s = parse_hhmm(arm_at)
            checks.append(_c("arm.warbell", True, f"armed for {h:02d}:{m:02d}:{s:02d}"))
        except Exception as exc:
            checks.append(_c("arm.warbell", False, f"bad arm_at: {exc}"))
    _brute = getattr(cfg, "brute", None)
    _lvl = _brute.level if _brute is not None else 4
    if is_void(_lvl):
        checks.append(
            _c(
                "brute.void",
                True,
                f"{title_for_level(cfg.brute.level)} — VOID MODE: no doomsday, "
                "no pacer, immortal retries, omni-captcha. NO MERCY.",
                level="ok",
            )
        )
    try:
        from camoufox.pkgman import installed_verstr

        checks.append(_c("browser.binaries", True, str(installed_verstr())))
    except Exception:
        checks.append(_c("browser.binaries", False, "missing — run: camoufox fetch"))

    ok = all(c["ok"] or c["level"] == "warn" for c in checks)
    return PreflightResult(ok, checks)
