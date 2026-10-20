"""BRUTE engine + ULTIMATE GOD upgrades — resilient primitives for every tool.

Design (inspired by the sample grabber script):
  * NEVER trust exact DOM structure — search the whole page by visible TEXT.
  * Random human delays between every action, mouse wiggle before clicks.
  * Every action retries with: re-find -> reload page -> re-login -> retry.
  * Any captcha anywhere on the page gets auto-solved (OCR -> service).
  * Every failure saves screenshots; every run saves a report to ./reports/.

GOD upgrades (brutality >= 3):
  * Self-healing selectors: SelectorMemory learns which strategy works per
    action and tries winners first — across runs.
  * Fuzzy fallback: "Submitt", "SUBMIT »", "Get Statuss" still match.
  * Block/ban detection + session keepalive inside every retry ladder.
  * Diagnostics black-box bundle on ultimate failure (secrets redacted).
  * Level 5: screenshot every step, max retries, no mercy.

If it is not BRUTE, it starves and dies. So this is BRUTE. TOO MUCH BRUTE.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..browser import launch_browser
from ..captcha.manager import AutoCaptcha
from ..god.diagnostics import save_bundle
from ..god.genome import Genome
from ..god.infinite import is_void, void_behavior
from ..god.journal import Journal
from ..god.memory import SelectorMemory
from ..god.pacer import Pacer
from ..god.signals import (
    best_match,
    detect_block,
    detect_session_dead,
    escalate_delay,
    looks_like_browser_death,
    tier_of,
    title_for_level,
)
from ..utils import ensure_dir, human_delay, save_bytes, save_screenshot, timestamp

log = logging.getLogger("ticket_booker.tools")

CAPTCHA_IMG_SELS = (
    "img[src*='captcha' i]",
    "img.captcha-img",
    "img#captchaImg",
    "img[alt*='captcha' i]",
)
CAPTCHA_INPUT_SELS = (
    "input[formcontrolname='captcha']",
    "input[formcontrolname='captchaInput']",
    "input[placeholder*='captcha' i]",
    "input[name*='captcha' i]",
    "input[id*='captcha' i]",
)

# Minimum ladder retries per brutality level (god raises the floor)
MIN_RETRIES = {1: 1, 2: 2, 3: 3, 4: 4, 5: 6}


class BlockedError(Exception):
    """Raised when the site is actively blocking us (ban/rate-limit/wall)."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Blocked: {reason}")
        self.reason = reason


@dataclass
class ToolResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    report_path: str = ""


def _plain_run(cfg, headless: bool | None, fn: Callable, *args, **kwargs):
    """One Camoufox session, no god ladder (used BY the god ladder)."""
    with launch_browser(cfg.browser, headless) as session:
        ctx = BruteContext(cfg, session.page, headless or cfg.browser.headless)
        try:
            from ..god.session_vault import load_vault

            load_vault(session.context)  # instant login for fresh heads
        except Exception as exc:
            log.debug("vault load skipped: %s", exc)
        return fn(ctx, *args, **kwargs)


def run_with_browser(cfg, headless: bool | None, fn: Callable, *args, **kwargs):
    """Open Camoufox session(s) and run fn(BruteContext, *args).

    Brutality >= 4 routes through the GOD relaunch ladder (fresh browser +
    proxy rotation). Lower levels run a single session.
    """
    level = int(getattr(getattr(cfg, "brute", None), "level", 3) or 3)
    brute_cfg = getattr(cfg, "brute", None)
    arm_at = str(getattr(brute_cfg, "arm_at", "") or "").strip()
    if arm_at:
        from ..god.chronos import arm_until

        arm_until(arm_at, lead=float(getattr(brute_cfg, "arm_lead_seconds", 5) or 0))
    if level >= 4:
        from ..god.engine import god_run
        from ..god.hydra import heads_for, hydra_race
        from ..god.signals import tier_of as _tier_of

        if _tier_of(level) >= 6 and heads_for(cfg) > 1:
            log.info("🐲 HYDRA: %d heads racing...", heads_for(cfg))
            return hydra_race(cfg, headless, lambda ctx: fn(ctx, *args, **kwargs))
        return god_run(cfg, headless, lambda ctx: fn(ctx, *args, **kwargs))
    return _plain_run(cfg, headless, fn, *args, **kwargs)


class BruteContext:
    """A page + config + captcha solver with brute-force god helpers."""

    def __init__(self, cfg, page, headless: bool = False) -> None:
        self.cfg = cfg
        self.page = page
        self.headless = headless
        self.captcha = AutoCaptcha(cfg.captcha)
        if page is not None:
            try:
                self.captcha.attach_page(page)
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("captcha page attach skipped: %s", exc)
        self.reports_dir = ensure_dir("./reports")
        self.shots_dir = ensure_dir("./screenshots/tools")
        self.diag_dir = ensure_dir("./diagnostics")
        self.journal = Journal()

        brute = getattr(cfg, "brute", None)
        self.brutality: int = int(getattr(brute, "level", 3) or 3)
        mem_file = getattr(brute, "memory_file", "") or "./profiles/selector_memory.json"
        self.memory = SelectorMemory(mem_file) if self.brutality >= 3 else None
        self.keepalive = bool(getattr(brute, "keepalive_checks", True)) and self.brutality >= 2
        self.diagnostics_on = bool(getattr(brute, "diagnostics", True))
        self._last_captcha_hash: str | None = None
        self._same_captcha_count = 0
        self._relogins_this_run = 0
        self.tier = tier_of(self.brutality)
        self.void = is_void(self.brutality)
        self.pacer = None if self.void else (Pacer() if self.tier >= 6 else None)
        self.genome: Genome | None = None
        if self.tier >= 7:
            try:
                self.genome = Genome(str(Path(mem_file).with_name("genome.json")))
                log.info("🧬 GENOME online - %d strategy DNA strands, best: %s",
                         len(self.genome.stats), self.genome.best() or "none yet")
            except Exception as exc:
                log.debug("genome disabled: %s", exc)
        try:
            _mins = int(getattr(brute, "max_tool_minutes", 0) or 0)
        except (TypeError, ValueError):
            _mins = 0
        self._deadline = (
            None
            if self.void
            else (time.time() + _mins * 60 if _mins > 0 else None)
        )
        log.info("⚡ BRUTE GOD engine engaged (level %s: %s)",
                 self.brutality, title_for_level(self.brutality))

    # ---------------- core navigation ----------------

    def goto(self, *urls: str, wait: tuple[float, float] = (2.0, 4.0)) -> bool:
        """Try URLs in order until one loads. Returns False if all fail."""
        for url in urls:
            for attempt in range(3):
                try:
                    log.info("🌐 Opening %s (try %d)", url, attempt + 1)
                    self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    human_delay(*wait)
                    self.dismiss_popups()
                    if self.brutality >= 5:
                        self.shot("goto")
                    try:
                        self.journal.event("goto", url, ok=True)
                    except Exception:
                        pass
                    return True
                except Exception as exc:
                    log.warning("goto %s failed: %s", url, exc)
                    try:
                        self.journal.event("goto", url, ok=False, extra=str(exc)[:150])
                    except Exception:
                        pass
                    human_delay(1.0, 2.5)
        return False

    def reload(self) -> None:
        try:
            self.page.reload(wait_until="domcontentloaded", timeout=45000)
            human_delay(1.5, 3.0)
            self.dismiss_popups()
        except Exception as exc:
            log.debug("reload failed: %s", exc)

    def dismiss_popups(self) -> None:
        for sel in (
            "button:has-text('OK')", "button:has-text('Yes')", "button:has-text('Close')",
            "button:has-text('Allow')", ".ui-dialog-titlebar-close", "button.close",
            "[aria-label='Close']",
        ):
            try:
                loc = self.page.locator(sel).first
                if loc.count() and loc.is_visible(timeout=400):
                    loc.click(timeout=2000)
                    time.sleep(0.4)
            except Exception:
                continue

    def shot(self, name: str) -> None:
        save_screenshot(self.page, name, self.shots_dir)

    # ---------------- self-healing strategy runner ----------------

    def _order(self, key: str, strategies: list[tuple[str, Callable]]) -> list[tuple[str, Callable]]:
        if not self.memory:
            return strategies
        pref = self.memory.preferred(key)
        if pref is None:
            return strategies
        ordered = sorted(strategies, key=lambda s: 0 if s[0] == pref else 1)
        if self.tier >= 6 and len(ordered) > 2 and random.random() < 0.2:
            head, tail = ordered[:1], ordered[1:]
            random.shuffle(tail)  # radioactive mutation: escape local minima
            ordered = head + tail
        if self.genome is not None and len(ordered) > 1 and random.random() < 0.4:
            pick = self.genome.choose([sid for sid, _ in ordered])
            ordered.sort(key=lambda s: 0 if s[0] == pick else 1)  # stable, keeps mutation
        return ordered

    def _record_win(self, key: str, sid: str) -> None:
        if self.memory:
            try:
                self.memory.record(key, sid)
            except Exception:
                pass
        if self.genome is not None:
            try:
                self.genome.record(sid, 1.0)  # strategy DNA learns who won
            except Exception:
                pass

    def _first_visible(self, sel: str, timeout: int = 900):
        """Locator if visible, else None. Never raises."""
        try:
            loc = self.page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=timeout):
                return loc
        except Exception:
            pass
        return None

    def _wiggle(self, loc) -> None:
        """Human mouse drift toward the element (god stealth, level 3+)."""
        if self.brutality < 3:
            return
        try:
            box = loc.bounding_box(timeout=1500)
            if not box:
                return
            x = box["x"] + box["width"] / 2 + random.uniform(-8, 8)
            y = box["y"] + box["height"] / 2 + random.uniform(-5, 5)
            self.page.mouse.move(max(1, x), max(1, y), steps=random.randint(8, 22))
            time.sleep(random.uniform(0.05, 0.3))
        except Exception:
            pass

    def _scroll_click(self, loc, force: bool = False, what: str = "") -> bool:
        try:
            _t0 = time.time()
            loc.scroll_into_view_if_needed(timeout=3000)
            self._wiggle(loc)
            human_delay(0.2, 0.8)
            loc.click(timeout=6000, force=force)
            if what:
                log.info("🖱️ Clicked '%s'", what)
            try:
                self.journal.event("click", what or "?", ok=True)
            except Exception:
                pass
            if self.pacer is not None:
                self.pacer.record(time.time() - _t0)
                self.pacer.sleep()
            if self.brutality >= 5:
                self.shot("click")
            return True
        except Exception as exc:
            log.debug("click '%s' failed: %s", what, exc)
            try:
                self.journal.event("click", what or "?", ok=False)
            except Exception:
                pass
            return False

    # ---------------- BRUTE text-first finders ----------------

    def page_text(self) -> str:
        try:
            return self.page.locator("body").inner_text(timeout=8000) or ""
        except Exception:
            return ""

    def has_text(self, *phrases: str) -> str | None:
        """Return first phrase found anywhere on the page (case-insensitive)."""
        body = self.page_text().lower()
        for p in phrases:
            if p.lower() in body:
                return p
        return None

    def wait_text(self, *phrases: str, timeout_s: int = 30) -> str | None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            hit = self.has_text(*phrases)
            if hit:
                return hit
            time.sleep(0.7)
        return None

    def find_text(self, *phrases: str):
        """Whole-page text search -> first visible locator, or None."""
        for phrase in phrases:
            key = f"find:{phrase.lower()}"
            strategies: list[tuple[str, Callable]] = [
                ("text", lambda p=phrase: self._first_visible(f"text={p!r}", 900)),
                ("filter", lambda p=phrase: self._filter_text(p)),
                ("xpath", lambda p=phrase: self._xpath_text(p)),
            ]
            for sid, thunk in self._order(key, strategies):
                try:
                    loc = thunk()
                except Exception:
                    continue
                if loc is not None:
                    self._record_win(key, sid)
                    return loc
        # GOD fuzzy fallback: match a *similar* visible line
        if self.brutality >= 3:
            return self._fuzzy_find(phrases)
        return None

    def _filter_text(self, phrase: str):
        for container in ("div", "span", "td", "li", "p", "h1", "h2", "h3", "h4",
                          "a", "button", "th", "label"):
            try:
                loc = self.page.locator(container).filter(has_text=phrase).first
                if loc.count() and loc.is_visible(timeout=600):
                    return loc
            except Exception:
                continue
        return None

    def _xpath_text(self, phrase: str):
        safe = phrase.replace("'", "")
        xp = f"//*[contains(normalize-space(.), '{safe}') and not(self::script) and not(self::style)]"
        return self._first_visible(f"xpath={xp}", 900)

    def _fuzzy_find(self, phrases: tuple[str, ...]):
        try:
            lines = [ln.strip() for ln in self.page_text().splitlines()]
            lines = [ln for ln in lines if 2 <= len(ln) <= 80][:400]
            for phrase in phrases:
                hit = best_match(phrase, lines, cutoff=0.72)
                if hit:
                    log.info("🔮 Fuzzy-matched '%s' -> '%s'", phrase, hit[0][:60])
                    return self._first_visible(f"text={hit[0]!r}", 1200)
        except Exception as exc:
            log.debug("fuzzy find failed: %s", exc)
        return None

    def click_text(self, *phrases: str, timeout_each: int = 2500, verify_change: bool = False) -> bool:
        """Click anything (button/link/tab/cell) showing one of the phrases."""
        for phrase in phrases:
            key = f"click:{phrase.lower()}"
            sels = [
                f"button:has-text('{phrase}')",
                f"a:has-text('{phrase}')",
                f"input[value*='{phrase}']",
                f"[role='button']:has-text('{phrase}')",
                f"[role='tab']:has-text('{phrase}')",
            ]
            strategies: list[tuple[str, Callable]] = [
                (f"sel{i}", (lambda s: lambda: self._first_visible(s))(s)) for i, s in enumerate(sels)
            ]
            strategies.append(("filter", lambda p=phrase: self._filter_clickable(p)))
            strategies.append(("xpath", lambda p=phrase: self._xpath_clickable(p)))
            for sid, thunk in self._order(key, strategies):
                try:
                    loc = thunk()
                except Exception:
                    continue
                if loc is None:
                    continue
                before = self._page_signature() if verify_change else None
                if self._scroll_click(loc, force=sid in ("filter", "xpath"), what=phrase):
                    if verify_change and not self._verify_changed(before):
                        log.info("👻 Click had no effect — escalating strategy...")
                        continue
                    self._record_win(key, sid)
                    return True
        if self.brutality >= 3 and self._fuzzy_click(phrases):
            return True
        log.warning("click_text found none of %s", phrases)
        return False

    def _filter_clickable(self, phrase: str):
        try:
            loc = self.page.locator("button, a, div, span, td, li").filter(has_text=phrase).first
            if loc.count() and loc.is_visible(timeout=1200):
                return loc
        except Exception:
            pass
        return None

    def _xpath_clickable(self, phrase: str):
        safe = phrase.replace("'", "")
        xp = (
            "//*[self::button or self::a or self::input or @role='button' or @role='tab']"
            f"[contains(normalize-space(.), '{safe}') or contains(@value, '{safe}')]"
        )
        return self._first_visible(f"xpath={xp}", 1200)

    def _page_signature(self):
        try:
            url = str(self.page.url)
        except Exception:
            url = "?"
        try:
            n = len(self.page.locator("body").inner_text(timeout=4000) or "")
        except Exception:
            n = -1
        pix = ""
        if self.tier >= 6:
            try:
                data = self.page.screenshot(timeout=4000)
                pix = hashlib.md5(data).hexdigest()[:12] if data else ""
            except Exception:
                pix = ""
        return (url, n, pix)

    def _verify_changed(self, before, timeout_s: int = 6) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self._page_signature() != before:
                return True
            time.sleep(0.5)
        return False

    def _fuzzy_click(self, phrases: tuple[str, ...]) -> bool:
        try:
            loc = self.page.locator(
                "button, a, input[type=submit], input[type=button], [role=button], [role=tab]"
            )
            n = min(loc.count(), 80)
            texts: list[str] = []
            for i in range(n):
                try:
                    el = loc.nth(i)
                    t = ((el.inner_text(timeout=700) or "") + " " + (el.get_attribute("value") or "")).strip()
                    texts.append(t)
                except Exception:
                    texts.append("")
            options = [t for t in texts if t]
            for phrase in phrases:
                hit = best_match(phrase, options, cutoff=0.6)
                if hit:
                    log.info("🔮 Fuzzy-click '%s' -> '%s'", phrase, hit[0][:60])
                    el = loc.nth(texts.index(hit[0]))
                    if el.count() and self._scroll_click(el, force=True, what=hit[0][:40]):
                        return True
        except Exception as exc:
            log.debug("fuzzy click failed: %s", exc)
        return False

    def fill_near_text(self, label_phrases: tuple[str, ...] | list[str], value: str) -> bool:
        """Find an input box by its label/placeholder/text and fill it. BRUTE."""
        for label in label_phrases:
            key = f"fill:{label.lower()}"
            safe = label.replace("'", "")
            strategies: list[tuple[str, Callable]] = [
                ("label", lambda l=label: self._by_label(l)),
                ("placeholder", lambda l=label: (
                    self._first_visible(f"input[placeholder*='{l}' i]", 700)
                    or self._first_visible(f"textarea[placeholder*='{l}' i]", 700)
                )),
                ("xpath-follow", lambda s=safe: self._first_visible(
                    f"xpath=//*[contains(normalize-space(.), '{s}')]"
                    "/following::input[not(@type='hidden' or @type='checkbox' or @type='radio')][1]", 900)),
                ("xpath-child", lambda s=safe: self._first_visible(
                    f"xpath=//*[contains(normalize-space(.), '{s}')]"
                    "//input[not(@type='hidden' or @type='checkbox' or @type='radio')][1]", 900)),
            ]
            for sid, thunk in self._order(key, strategies):
                try:
                    loc = thunk()
                except Exception:
                    continue
                if loc is not None and self._do_fill(loc, value, label):
                    self._record_win(key, sid)
                    return True
        if self.brutality >= 3 and self._fuzzy_fill(label_phrases, value):
            return True
        log.warning("fill_near_text found no input for %s", label_phrases)
        return False

    def _by_label(self, label: str):
        try:
            loc = self.page.get_by_label(label, exact=False).first
            if loc.count() and loc.is_visible(timeout=700):
                return loc
        except Exception:
            pass
        return None

    def _fuzzy_fill(self, labels, value: str) -> bool:
        try:
            cands: list[str] = []
            try:
                labs = self.page.locator("label")
                for i in range(min(labs.count(), 60)):
                    try:
                        cands.append(labs.nth(i).inner_text(timeout=600) or "")
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                ins = self.page.locator("input, textarea")
                for i in range(min(ins.count(), 60)):
                    try:
                        cands.append(ins.nth(i).get_attribute("placeholder") or "")
                        cands.append(ins.nth(i).get_attribute("aria-label") or "")
                        cands.append(ins.nth(i).get_attribute("name") or "")
                    except Exception:
                        pass
            except Exception:
                pass
            options = [c.strip() for c in cands if c and c.strip()]
            for label in labels:
                hit = best_match(label, options, cutoff=0.6)
                if hit:
                    log.info("🔮 Fuzzy-fill '%s' -> '%s'", label, hit[0][:50])
                    loc = (self._by_label(hit[0])
                           or self._first_visible(f"input[placeholder*='{hit[0]}' i]", 900)
                           or self._first_visible(f"textarea[placeholder*='{hit[0]}' i]", 900))
                    if loc is not None and self._do_fill(loc, value, label):
                        return True
        except Exception as exc:
            log.debug("fuzzy fill failed: %s", exc)
        return False

    def _do_fill(self, loc, value: str, label: str) -> bool:
        try:
            loc.scroll_into_view_if_needed(timeout=3000)
            self._wiggle(loc)
            loc.click(timeout=4000)
            try:
                loc.fill("", timeout=2500)
            except Exception:
                loc.press("ControlOrMeta+a")
                loc.press("Backspace")
            time.sleep(0.3)
            loc.press_sequentially(value, delay=random.randint(20, 70), timeout=12000)
            log.info("⌨️ Filled '%s'", label)
            try:
                self.journal.event("fill", label, ok=True)
            except Exception:
                pass
            if self.pacer is not None:
                self.pacer.sleep()
            if self.brutality >= 5:
                self.shot("fill")
            return True
        except Exception as exc:
            log.debug("fill '%s' failed: %s", label, exc)
            try:
                self.journal.event("fill", label, ok=False)
            except Exception:
                pass
            return False

    def table_texts(self, max_tables: int = 6, max_rows: int = 60) -> list[list[list[str]]]:
        """Dump all tables on the page as text (brute data extraction)."""
        tables: list[list[list[str]]] = []
        try:
            n = self.page.locator("table").count()
        except Exception:
            return tables
        for ti in range(min(n, max_tables)):
            rows: list[list[str]] = []
            try:
                tbl = self.page.locator("table").nth(ti)
                rn = tbl.locator("tr").count()
                for ri in range(min(rn, max_rows)):
                    cells = []
                    try:
                        cn = tbl.locator("tr").nth(ri).locator("th, td").count()
                        for ci in range(min(cn, 20)):
                            try:
                                cells.append(
                                    (tbl.locator("tr").nth(ri).locator("th, td").nth(ci).inner_text(timeout=1500) or "").strip()
                                )
                            except Exception:
                                cells.append("")
                    except Exception:
                        continue
                    if any(cells):
                        rows.append(cells)
            except Exception:
                continue
            if rows:
                tables.append(rows)
        return tables

    # ---------------- BRUTE captcha: solve ANY captcha on the page ----------------

    def solve_captchas_on_page(self, max_rounds: int = 3) -> int:
        """Find every captcha img + fill its answer. Returns # solved."""
        solved = 0
        for _ in range(max_rounds):
            img_loc = None
            for sel in CAPTCHA_IMG_SELS:
                try:
                    loc = self.page.locator(sel).first
                    if loc.count() and loc.is_visible(timeout=900):
                        img_loc = loc
                        break
                except Exception:
                    continue
            if img_loc is None:
                break
            try:
                img_loc.scroll_into_view_if_needed(timeout=3000)
                img_bytes = img_loc.screenshot(timeout=6000)
            except Exception as exc:
                log.debug("captcha screenshot failed: %s", exc)
                break
            # GOD: identical image after refresh = refresh control is fake; reload.
            digest = hashlib.md5(img_bytes).hexdigest()
            if digest == self._last_captcha_hash:
                self._same_captcha_count += 1
                if self._same_captcha_count >= 2:
                    log.warning("🔐 Captcha image unchanged after refresh — reloading page...")
                    self.reload()
                    self._same_captcha_count = 0
                    human_delay(1.5, 3.0)
                    continue
            else:
                self._last_captcha_hash = digest
                self._same_captcha_count = 0
            try:
                save_bytes(img_bytes, "tool_captcha.png", self.cfg.captcha.debug_dir)
            except Exception:
                pass
            res = self.captcha.solve_text_image(img_bytes)
            if not res.ok:
                log.warning("🔐 OCR blank — refreshing captcha and retrying...")
                self.click_text("Try Another", "Refresh", "Reload", "New Captcha")
                human_delay(1.0, 2.0)
                continue
            filled = False
            for sel in CAPTCHA_INPUT_SELS:
                try:
                    box = self.page.locator(sel).first
                    if box.count() and box.is_visible(timeout=900):
                        filled = self._do_fill(box, res.text, "captcha")
                        break
                except Exception:
                    continue
            if not filled:
                try:
                    box = self.page.locator("input[type='text'], input:not([type])").last
                    if box.count():
                        filled = self._do_fill(box, res.text, "captcha")
                except Exception:
                    pass
            if filled:
                solved += 1
                log.info("🔓 Captcha auto-filled (%s).", res.solver)
                try:
                    self.journal.event("captcha", res.solver, ok=True)
                except Exception:
                    pass
                human_delay(0.5, 1.2)
            else:
                log.warning("Captcha found but no input box — stopping.")
                break
        try:
            if self.cfg.captcha.recaptcha_audio.enabled or getattr(
                getattr(self.cfg.captcha, "buster", None), "enabled", False
            ):
                self.captcha.solve_recaptcha(self.page)
        except Exception as exc:
            log.debug("recaptcha check skipped: %s", exc)
        return solved

    # ---------------- GOD keepalive + retry ladder ----------------

    def _heartbeat(self) -> None:
        """Cooperative keepalive: block/ban/session probe before each attempt.

        Raises BlockedError on hard blocks (god ladder rotates proxy /
        relaunches). Auto re-logs on dead sessions (max 2 per context).
        """
        if not self.keepalive:
            return
        try:
            text = self.page_text()
        except Exception:
            return  # page unreadable — the ladder's reload will handle it
        reason = detect_block(text)
        if reason:
            self.shot("blocked")
            raise BlockedError(reason)
        if detect_session_dead(text) and self._relogins_this_run < 2:
            log.warning("💤 Keepalive: session looks dead — re-logging in...")
            self._relogins_this_run += 1
            self.ensure_login()

    def brute(
        self,
        fn: Callable[[], Any],
        what: str,
        retries: int = 3,
        reload_between: bool = True,
        relogin_once: bool = False,
    ) -> Any:
        """Run fn with the GOD ladder: heartbeat -> run -> reload -> re-login.

        God raises the retry floor by brutality. Browser death aborts the
        ladder immediately so god_run() can relaunch a FRESH browser instead
        of flogging a corpse. Ultimate failure writes a diagnostics bundle.
        """
        floor = MIN_RETRIES.get(min(self.brutality, 5), 3)
        if self.tier >= 6:
            floor = max(floor, 7)
        if self.tier >= 7:
            floor = max(floor, 9)
        if self.void:
            floor = max(floor, 50)  # VOID: uncapped immortal ladder
        retries = max(int(retries), floor)
        last: Exception | None = None
        relogged = False
        for attempt in range(1, retries + 1):
            if (
                not self.void
                and self._deadline
                and time.time() > self._deadline
            ):
                raise TimeoutError(f"DOOMSDAY: exceeded max_tool_minutes budget during '{what}'")
            try:
                if attempt > 1:
                    log.info("🔁 %s — brute attempt %d/%d", what, attempt, retries)
                self._heartbeat()
                _t0 = time.time()
                _out = fn()
                try:
                    self.journal.event("brute", what, ok=True, ms=int((time.time() - _t0) * 1000))
                except Exception:
                    pass
                return _out
            except BlockedError:
                raise
            except Exception as exc:
                last = exc
                if looks_like_browser_death(exc):
                    log.error("💀 Browser died mid-ladder — aborting for fresh relaunch.")
                    raise
                log.warning("⚠️ %s failed (attempt %d): %s", what, attempt, str(exc)[:200])
                self.shot(f"brute_fail_{re.sub(r'[^a-z0-9]+', '_', what.lower())}_{attempt}")
                if relogin_once and not relogged and attempt >= 2:
                    relogged = True
                    self.ensure_login()
                if reload_between and attempt < retries:
                    self.reload()
                if attempt < retries:
                    time.sleep(escalate_delay(attempt))
        assert last is not None
        try:
            self.journal.event("brute", what, ok=False, extra=str(last)[:200])
        except Exception:
            pass
        self._save_diagnostics(what, last)
        raise last

    def _save_diagnostics(self, what: str, exc: BaseException) -> None:
        if not self.diagnostics_on:
            return
        try:
            save_bundle(
                self.diag_dir, f"{what}_FAILED",
                page=self.page,
                extra={"error": str(exc)[:1000],
                       "traceback": traceback.format_exc()[-6000:],
                       "config": self.cfg},
            )
        except Exception as e2:
            log.debug("diagnostics failed: %s", e2)

    def ensure_login(self) -> bool:
        """Make sure IRCTC session is alive; login (auto captcha) if not."""
        from ..irctc.login import is_logged_in, login

        try:
            if is_logged_in(self.page):
                return True
        except Exception:
            pass
        log.info("🔑 Session dead — re-logging in (auto captcha)...")
        try:
            ok = login(self.page, self.cfg.irctc, self.captcha, headless=self.headless)
            if ok:
                try:
                    from ..god.session_vault import save_vault

                    save_vault(self.page.context)
                except Exception as exc2:
                    log.debug("vault save skipped: %s", exc2)
            return ok
        except Exception as exc:
            log.error("Re-login failed: %s", exc)
            return False

    # ---------------- reports (sample-script style: always save to file) ----------------

    def save_report(self, name: str, data: dict[str, Any], summary: str = "") -> Path:
        stamp = timestamp()
        payload = {"tool": name, "saved_on": stamp, "data": data}
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", name)
        jpath = self.reports_dir / f"{stamp}_{safe}.json"
        jpath.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        text = summary or json.dumps(payload, indent=2, ensure_ascii=False)
        (self.reports_dir / f"{stamp}_{safe}.txt").write_text(text, encoding="utf-8")
        log.info("💾 Report saved → %s", jpath)
        return jpath
