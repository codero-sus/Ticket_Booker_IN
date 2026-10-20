"""IRCTC login with zero-touch captcha solving.

Flow:
  1. If already logged in (persistent profile session), skip.
  2. Open LOGIN modal, fill username/password once.
  3. Loop up to captcha.max_attempts:
       screenshot captcha img -> AutoCaptcha -> fill -> SIGN IN
       * success -> done
       * "invalid credentials" -> raise (fix config, don't burn attempts)
       * captcha error -> refresh image, retry
  4. If all auto attempts fail and on_failure=manual (headed): pause and let
     the user solve it once in the browser, then continue automatically.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from ..captcha.manager import AutoCaptcha
from ..captcha.recaptcha_solver import solve_recaptcha_if_present
from ..config import CaptchaCfg, IrctcAuth
from ..utils import human_delay, save_bytes, save_screenshot
from . import constants as C
from .helpers import click_first, dismiss_popups, fill_first, locate_first, page_text

log = logging.getLogger("ticket_booker.irctc.login")


def is_logged_in(page) -> bool:
    """Logged in = LOGIN modal gone AND a logout/account marker visible."""
    try:
        modal = locate_first(page, C.LOGIN_MODAL, timeout_each=400)
        if modal is not None:
            return False
        return locate_first(page, C.LOGGED_IN_MARKERS, timeout_each=600) is not None
    except Exception:
        return False


def open_login_modal(page) -> bool:
    if locate_first(page, C.LOGIN_MODAL, timeout_each=600) is not None:
        return True
    dismiss_popups(page)
    if not click_first(page, C.LOGIN_BUTTON, timeout_each=2500):
        log.error("Could not find the LOGIN button. Screenshot taken for debug.")
        save_screenshot(page, "no_login_button")
        return False
    deadline = time.time() + 12
    while time.time() < deadline:
        if locate_first(page, C.USERNAME_INPUT, timeout_each=600) is not None:
            return True
        time.sleep(0.5)
    log.error("LOGIN modal did not open.")
    return False


def get_captcha_bytes(page) -> bytes | None:
    img = locate_first(page, C.CAPTCHA_IMG, timeout_each=2500)
    if img is None:
        return None
    try:
        img.scroll_into_view_if_needed(timeout=3000)
        return img.screenshot(timeout=5000)
    except Exception as exc:
        log.debug("Captcha screenshot failed: %s", exc)
        return None


def refresh_captcha(page) -> None:
    if not click_first(page, C.CAPTCHA_REFRESH, timeout_each=1200):
        # Fallback: re-open modal to get a fresh captcha
        log.debug("No refresh control; pressing Escape + reopening modal.")
        try:
            page.keyboard.press("Escape")
            time.sleep(0.6)
            open_login_modal(page)
        except Exception:
            pass
    time.sleep(1.0)


def _verdict_after_submit(page, timeout_s: int = 12) -> str:
    """Return 'ok' | 'captcha' | 'credentials' | 'unknown'."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if is_logged_in(page):
            return "ok"
        body = page_text(page).lower()
        if any(t.lower() in body for t in C.INVALID_CREDENTIALS_TEXT):
            return "credentials"
        if any(t.lower() in body for t in C.INVALID_CAPTCHA_TEXT):
            return "captcha"
        time.sleep(0.6)
    # One last check — slow networks can lag the verdict
    if is_logged_in(page):
        return "ok"
    body = page_text(page).lower()
    if any(t.lower() in body for t in C.INVALID_CAPTCHA_TEXT):
        return "captcha"
    if any(t.lower() in body for t in C.INVALID_CREDENTIALS_TEXT):
        return "credentials"
    return "unknown"


def _manual_fallback(page, captcha_cfg: CaptchaCfg, timeout_s: int = 180) -> bool:
    """Pause for the user to solve the captcha once in the open browser."""
    log.warning(
        "Auto captcha failed. PLEASE SOLVE the captcha in the browser window "
        "and click SIGN IN yourself — waiting up to %ds...", timeout_s
    )
    try:
        print("\n>>> Solve the IRCTC captcha in the browser, click SIGN IN,")
        print(">>> then press ENTER here (or just wait for auto-detect).")
        import threading

        done = threading.Event()

        def _wait_enter():
            try:
                input()
            except EOFError:
                pass
            done.set()

        threading.Thread(target=_wait_enter, daemon=True).start()
        deadline = time.time() + timeout_s
        while time.time() < deadline and not done.is_set():
            if is_logged_in(page):
                return True
            time.sleep(1.0)
        return is_logged_in(page)
    except Exception:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if is_logged_in(page):
                return True
            time.sleep(1.0)
        return is_logged_in(page)


def login(
    page,
    auth: IrctcAuth,
    captcha: AutoCaptcha,
    headless: bool = False,
    timeout_s: int = 240,
) -> bool:
    """Ensure logged in. Returns True on success, raises on fatal errors."""
    if not auth.username or not auth.password:
        raise ValueError("IRCTC username/password missing (config or IRCTC_USER/IRCTC_PASS).")

    # Gemini Nano lives inside this page - hand it over before the captcha loop.
    attach = getattr(captcha, "attach_page", None)
    if attach is not None:
        try:
            attach(page)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("captcha page attach skipped: %s", exc)

    page.goto(C.HOME_URL, wait_until="domcontentloaded")
    human_delay(1.0, 2.0)
    dismiss_popups(page)
    # Buster bridge: clicks the icon, then PLAY. No-op when there is no
    # reCAPTCHA, and falls back to the legacy audio solver internally.
    try:
        solver = getattr(captcha, "solve_recaptcha", None)
        if solver is not None:
            res = solver(page)
            if not getattr(res, "solved", True):
                log.warning("reCAPTCHA not solved: %s", getattr(res, "message", ""))
        else:
            solve_recaptcha_if_present(page)
    except Exception as exc:  # never fatal during a booking race
        log.debug("reCAPTCHA pre-check skipped: %s", exc)

    if is_logged_in(page):
        log.info("Already logged in (reused saved session).")
        return True
    if not open_login_modal(page):
        raise RuntimeError("Could not open IRCTC login form.")

    # Fill credentials once (they persist across captcha retries)
    if not fill_first(page, C.USERNAME_INPUT, auth.username, timeout_each=4000):
        raise RuntimeError("Username field not found — IRCTC layout may have changed.")
    human_delay(0.2, 0.6)
    if not fill_first(page, C.PASSWORD_INPUT, auth.password, timeout_each=4000):
        raise RuntimeError("Password field not found — IRCTC layout may have changed.")

    cfg = captcha.cfg
    max_attempts = max(1, cfg.max_attempts)
    debug_dir = Path(cfg.debug_dir)
    deadline = time.time() + timeout_s

    for attempt in range(1, max_attempts + 1):
        if time.time() > deadline:
            break
        log.info("Login attempt %d/%d: solving captcha...", attempt, max_attempts)

        img_bytes = get_captcha_bytes(page)
        if img_bytes is None:
            log.warning("Captcha image not found; retrying modal...")
            save_screenshot(page, "no_captcha_img", debug_dir)
            refresh_captcha(page)
            continue
        try:
            save_bytes(img_bytes, "attempt_captcha.png", debug_dir)
        except Exception:
            pass

        result = captcha.solve_text_image(img_bytes)
        if not result.ok:
            log.info("Solver produced no reading; refreshing captcha...")
            refresh_captcha(page)
            continue

        if not fill_first(page, C.CAPTCHA_INPUT, result.text, timeout_each=3000):
            log.warning("Captcha input not found.")
            save_screenshot(page, "no_captcha_input", debug_dir)
            refresh_captcha(page)
            continue
        human_delay(0.3, 0.8)
        if not click_first(page, C.LOGIN_SUBMIT, timeout_each=2000):
            raise RuntimeError("SIGN IN button not found.")

        verdict = _verdict_after_submit(page)
        if verdict == "ok":
            log.info("IRCTC login successful.")
            return True
        if verdict == "credentials":
            save_screenshot(page, "bad_credentials", debug_dir)
            raise ValueError("IRCTC rejected username/password. Fix credentials and retry.")
        if verdict == "captcha":
            log.info("Captcha rejected, refreshing...")
            refresh_captcha(page)
            # Re-fill credentials in case the modal reset
            fill_first(page, C.USERNAME_INPUT, auth.username, timeout_each=1500)
            fill_first(page, C.PASSWORD_INPUT, auth.password, timeout_each=1500)
            continue
        log.warning("Unclear login result; refreshing and retrying...")
        save_screenshot(page, f"login_unknown_{attempt}", debug_dir)
        refresh_captcha(page)

    # All auto attempts exhausted
    save_screenshot(page, "login_auto_failed", debug_dir)
    if captcha.wants_manual_fallback and not headless:
        if _manual_fallback(page, cfg):
            log.info("Logged in after manual captcha assist.")
            return True
        raise RuntimeError("Manual captcha assist timed out.")
    raise RuntimeError(
        f"Login failed after {max_attempts} automatic attempts. "
        "Check screenshots in ./screenshots/captcha/ and try again."
    )
