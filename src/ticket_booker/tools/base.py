"""BRUTE engine — resilient primitives every scraper tool is built on.

Design (inspired by the sample grabber script):
  * NEVER trust exact DOM structure — search the whole page by visible TEXT
    (`filter(has_text=...)`, XPath contains(.,...)). If IRCTC moves a button
    from div #3 to div #9, text search still finds it.
  * Random human delays between every action (2-10s style), configurable.
  * Every action retries with: re-find -> reload page -> re-login -> retry.
  * Any captcha anywhere on the page gets auto-solved (OCR -> service).
  * Every failure saves screenshots; every run saves a report to ./reports/.

If it is not BRUTE, it starves and dies. So this is BRUTE.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..browser import launch_browser
from ..captcha.manager import AutoCaptcha
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


@dataclass
class ToolResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    report_path: str = ""


def run_with_browser(cfg, headless: bool | None, fn: Callable, *args, **kwargs):
    """Open one Camoufox session and run fn(BruteContext, *args)."""
    with launch_browser(cfg.browser, headless) as session:
        ctx = BruteContext(cfg, session.page, headless or cfg.browser.headless)
        return fn(ctx, *args, **kwargs)


class BruteContext:
    """A page + config + captcha solver with brute-force helpers."""

    def __init__(self, cfg, page, headless: bool = False) -> None:
        self.cfg = cfg
        self.page = page
        self.headless = headless
        self.captcha = AutoCaptcha(cfg.captcha)
        self.reports_dir = ensure_dir("./reports")
        self.shots_dir = ensure_dir("./screenshots/tools")

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
                    return True
                except Exception as exc:
                    log.warning("goto %s failed: %s", url, exc)
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

    # ---------------- BRUTE text-first finders ----------------
    # (the sample script's superpower: filter(has_text=...) over the whole page)

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
            # Strategy 1: Playwright text engine (fast, layout-proof)
            try:
                loc = self.page.get_by_text(phrase, exact=False).first
                if loc.count() and loc.is_visible(timeout=1200):
                    return loc
            except Exception:
                pass
            # Strategy 2: filter() over common containers (sample-script style)
            for container in ("div", "span", "td", "li", "p", "h1", "h2", "h3", "h4", "a", "button", "th", "label"):
                try:
                    loc = self.page.locator(container).filter(has_text=phrase).first
                    if loc.count() and loc.is_visible(timeout=700):
                        return loc
                except Exception:
                    continue
            # Strategy 3: XPath contains() — the last-resort brute hammer
            try:
                xp = (
                    f"//*[contains(normalize-space(.), '{phrase}') "
                    f"and not(self::script) and not(self::style)]"
                )
                loc = self.page.locator(f"xpath={xp}").first
                if loc.count() and loc.is_visible(timeout=1200):
                    return loc
            except Exception:
                pass
        return None

    def click_text(self, *phrases: str, timeout_each: int = 2500) -> bool:
        """Click anything (button/link/tab/cell) showing one of the phrases."""
        for phrase in phrases:
            # 1) proper buttons/links first (least likely to misclick)
            for sel in (
                f"button:has-text('{phrase}')",
                f"a:has-text('{phrase}')",
                f"input[value*='{phrase}']",
                f"[role='button']:has-text('{phrase}')",
                f"[role='tab']:has-text('{phrase}')",
            ):
                try:
                    loc = self.page.locator(sel).first
                    if loc.count() and loc.is_visible(timeout=900):
                        loc.scroll_into_view_if_needed(timeout=3000)
                        human_delay(0.3, 0.9)
                        loc.click(timeout=6000)
                        log.info("🖱️ Clicked '%s'", phrase)
                        return True
                except Exception:
                    continue
            # 2) sample-script style: filter over clickables
            try:
                loc = self.page.locator("button, a, div, span, td, li").filter(
                    has_text=phrase
                ).first
                if loc.count() and loc.is_visible(timeout=timeout_each):
                    loc.scroll_into_view_if_needed(timeout=3000)
                    human_delay(0.3, 0.9)
                    loc.click(timeout=6000, force=True)
                    log.info("🖱️ Clicked '%s' (via filter)", phrase)
                    return True
            except Exception:
                pass
            # 3) XPath hammer on clickables
            try:
                xp = (
                    f"//*[self::button or self::a or self::input or @role='button' or @role='tab']"
                    f"[contains(normalize-space(.), '{phrase}') or contains(@value, '{phrase}')]"
                )
                loc = self.page.locator(f"xpath={xp}").first
                if loc.count() and loc.is_visible(timeout=timeout_each):
                    loc.scroll_into_view_if_needed(timeout=3000)
                    loc.click(timeout=6000, force=True)
                    log.info("🖱️ Clicked '%s' (via xpath)", phrase)
                    return True
            except Exception:
                pass
        log.warning("click_text found none of %s", phrases)
        return False

    def fill_near_text(self, label_phrases: tuple[str, ...] | list[str], value: str) -> bool:
        """Find an input box by its label/placeholder/text and fill it. BRUTE."""
        for label in label_phrases:
            # 1) proper label association
            try:
                loc = self.page.get_by_label(label, exact=False).first
                if loc.count() and loc.is_visible(timeout=900):
                    return self._do_fill(loc, value, label)
            except Exception:
                pass
            # 2) placeholder match
            for sel in (
                f"input[placeholder*='{label}' i]",
                f"textarea[placeholder*='{label}' i]",
            ):
                try:
                    loc = self.page.locator(sel).first
                    if loc.count() and loc.is_visible(timeout=900):
                        return self._do_fill(loc, value, label)
                except Exception:
                    continue
            # 3) XPath: input following an element containing the label text
            try:
                xp = (
                    f"//*[contains(normalize-space(.), '{label}')]"
                    f"/following::input[not(@type='hidden' or @type='checkbox' or @type='radio')][1]"
                )
                loc = self.page.locator(f"xpath={xp}").first
                if loc.count() and loc.is_visible(timeout=1200):
                    return self._do_fill(loc, value, label)
            except Exception:
                pass
            # 4) XPath: input inside the same labelled container
            try:
                xp = (
                    f"//*[contains(normalize-space(.), '{label}')]"
                    f"//input[not(@type='hidden' or @type='checkbox' or @type='radio')][1]"
                )
                loc = self.page.locator(f"xpath={xp}").first
                if loc.count() and loc.is_visible(timeout=1200):
                    return self._do_fill(loc, value, label)
            except Exception:
                pass
        log.warning("fill_near_text found no input for %s", label_phrases)
        return False

    def _do_fill(self, loc, value: str, label: str) -> bool:
        try:
            loc.scroll_into_view_if_needed(timeout=3000)
            loc.click(timeout=4000)
            try:
                loc.fill("", timeout=2500)
            except Exception:
                loc.press("ControlOrMeta+a")
                loc.press("Backspace")
            time.sleep(0.3)
            loc.press_sequentially(value, delay=random.randint(20, 70), timeout=12000)
            log.info("⌨️ Filled '%s'", label)
            return True
        except Exception as exc:
            log.debug("fill '%s' failed: %s", label, exc)
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
                # Brute: any empty text input near the captcha image
                try:
                    box = self.page.locator("input[type='text'], input:not([type])").last
                    if box.count():
                        filled = self._do_fill(box, res.text, "captcha")
                except Exception:
                    pass
            if filled:
                solved += 1
                log.info("🔓 Captcha auto-filled (%s).", res.solver)
                human_delay(0.5, 1.2)
            else:
                log.warning("Captcha found but no input box — stopping.")
                break
        # Also handle reCAPTCHA if some gateway embeds it
        try:
            from ..captcha.recaptcha_solver import solve_recaptcha_if_present

            if self.cfg.captcha.recaptcha_audio.enabled:
                solve_recaptcha_if_present(
                    self.page,
                    language=self.cfg.captcha.recaptcha_audio.language,
                    max_audio_attempts=self.cfg.captcha.recaptcha_audio.max_audio_attempts,
                )
        except Exception as exc:
            log.debug("recaptcha check skipped: %s", exc)
        return solved

    # ---------------- BRUTE retry wrapper ----------------

    def brute(
        self,
        fn: Callable[[], Any],
        what: str,
        retries: int = 3,
        reload_between: bool = True,
        relogin_once: bool = False,
    ) -> Any:
        """Run fn with reload/re-login recovery. Raises last error if all fail."""
        last: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                if attempt > 1:
                    log.info("🔁 %s — brute attempt %d/%d", what, attempt, retries)
                return fn()
            except Exception as exc:
                last = exc
                log.warning("⚠️ %s failed (attempt %d): %s", what, attempt, exc)
                self.shot(f"brute_fail_{re.sub(r'[^a-z0-9]+', '_', what.lower())}_{attempt}")
                if relogin_once and attempt == 2:
                    self.ensure_login()
                if reload_between and attempt < retries:
                    self.reload()
                human_delay(1.5, 4.0)
        assert last is not None
        raise last

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
            return login(self.page, self.cfg.irctc, self.captcha, headless=self.headless)
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
