"""Buster bridge — drive the real Buster extension: click the icon, then PLAY.

Buster (https://github.com/dessant/buster) solves reCAPTCHA audio challenges
with speech recognition. Its content script runs inside the reCAPTCHA
*challenge* frame (``recaptcha/api2/bframe``) and injects a button:

    button#solver-button      <- the orange "buster" icon

Clicking that icon is the whole user gesture. Buster then does the rest by
itself, and we can watch it happen:

    #recaptcha-audio-button                  switch to the audio challenge
    .rc-audiochallenge-play-button > button  <- "PLAY"
    audio#audio-source                       the MP3 the challenge serves
    #audio-response                          where the transcript goes
    #recaptcha-verify-button                 submit

So "icon then PLAY" maps to two very concrete clicks. This module supports:

* ``mode="extension"`` — click ``#solver-button`` and let the real extension
  do the solving (exact Buster code path, exact Buster behaviour).
* ``mode="native"`` — no extension installed: perform the identical click
  sequence ourselves (audio -> PLAY -> download -> transcribe -> submit).
* ``mode="auto"`` (default) — use the icon when the extension is present,
  otherwise fall back to native. Always zero-touch.

Both paths are unit-tested against a fake page; no browser needed.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("ticket_booker.captcha.buster")

# --- selectors, taken verbatim from dessant/buster src/base/main.js -------- #
ICON_SELECTOR = "#solver-button"          # the buster icon inside bframe
AUDIO_TAB = "#recaptcha-audio-button"     # headphones
PLAY_SELECTOR = ".rc-audiochallenge-play-button > button"   # "PLAY"
AUDIO_SRC = "audio#audio-source"
ANSWER_INPUT = "#audio-response"
VERIFY_BUTTON = "#recaptcha-verify-button"
RELOAD_BUTTON = "#recaptcha-reload-button"
ANCHOR_CHECKBOX = "#recaptcha-anchor"

#: Universal fallbacks in case Google re-skins the widget.
PLAY_FALLBACKS = (
    PLAY_SELECTOR,
    "button.rc-audiochallenge-play-button",
    "#recaptcha-audio-play-button",
    "button[aria-label='Play']",
    "button[aria-label*='Play' i]",
)
ICON_FALLBACKS = (ICON_SELECTOR, "button#solver-button", "button[data-tooltip]")

DEFAULT_TIMEOUT = 60.0


@dataclass
class BusterResult:
    """Outcome of one attempt."""

    solved: bool
    method: str = "none"      # "extension" | "native" | "none"
    attempts: int = 0
    message: str = ""

    def __bool__(self) -> bool:  # `if result:` reads nicely in callers
        return self.solved


# --------------------------------------------------------------------------- #
# frame discovery (same iframe layout the plain solver uses)
# --------------------------------------------------------------------------- #

def _anchor_frame(page):
    try:
        for frame in page.frames:
            if "recaptcha/api2/anchor" in (frame.url or ""):
                return frame
    except Exception:
        pass
    return None


def _challenge_frame(page):
    try:
        for frame in page.frames:
            url = frame.url or ""
            if "recaptcha/api2/bframe" in url or "recaptcha/api2/mframe" in url:
                return frame
    except Exception:
        pass
    return None


def anchor_checked(anchor) -> bool:
    """True when the reCAPTCHA checkbox reports success."""
    if anchor is None:
        return False
    try:
        return anchor.locator(ANCHOR_CHECKBOX).get_attribute("aria-checked") == "true"
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# tiny locator helpers (tolerant, never raise)
# --------------------------------------------------------------------------- #

def _count(frame, selector: str) -> int:
    try:
        return int(frame.locator(selector).count())
    except Exception:
        return 0


def _click(frame, selector: str, timeout: float = 5000.0, force_js: bool = False) -> bool:
    """Click the first selector that exists. Falls back to a JS click."""
    try:
        loc = frame.locator(selector)
        if not loc.count():
            return False
        loc.first.click(timeout=timeout)
        return True
    except Exception as exc:
        log.debug("click %s failed (%s), trying JS", selector, exc)
    if not force_js:
        return False
    try:
        frame.evaluate(
            "(sel) => { const el = document.querySelector(sel);"
            " if (el) { el.click(); return true; } return false; }",
            selector,
        )
        return True
    except Exception:
        return False


def _click_first(frame, selectors, timeout: float = 5000.0) -> str:
    """Click the first present selector; return it ('' if none matched)."""
    for sel in selectors:
        if _count(frame, sel) and _click(frame, sel, timeout=timeout):
            return sel
    return ""


def _wait_for(frame, selector: str, timeout: float = 10000.0) -> bool:
    try:
        frame.wait_for_selector(selector, timeout=timeout, state="attached")
        return True
    except Exception:
        return False


def _poll(fn, timeout: float, interval: float = 0.5) -> bool:
    deadline = time.time() + max(0.0, timeout)
    while time.time() < deadline:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


# --------------------------------------------------------------------------- #
# the solver
# --------------------------------------------------------------------------- #

class BusterSolver:
    """Click the Buster icon, then PLAY — or do exactly what it would do."""

    name = "buster"

    def __init__(
        self,
        mode: str = "auto",
        timeout: float = DEFAULT_TIMEOUT,
        max_attempts: int = 3,
        solve_checkbox: bool = True,
        language: str = "en",
        page=None,
        poll_interval: float = 0.5,
        simulate_play: bool = True,
    ) -> None:
        self.mode = (mode or "auto").lower()
        self.timeout = float(timeout)
        self.max_attempts = max(1, int(max_attempts))
        self.solve_checkbox = bool(solve_checkbox)
        self.language = language
        self.page = page
        self.poll_interval = float(poll_interval)
        self.simulate_play = bool(simulate_play)
        self.last_method = "none"

    # ---------------- lifecycle ---------------- #

    def set_page(self, page) -> None:
        self.page = page

    attach_page = set_page

    def available(self) -> bool:
        return self.page is not None

    def availability_reason(self) -> str:
        return "" if self.available() else "buster: no page attached"

    # ---------------- capability probe ---------------- #

    def icon_present(self, page=None) -> bool:
        """True when the Buster extension has injected its icon into bframe."""
        frame = _challenge_frame(page or self.page)
        if frame is None:
            return False
        return any(_count(frame, sel) for sel in ICON_FALLBACKS)

    def status(self, page=None) -> dict:
        page = page or self.page
        return {
            "solver": self.name,
            "mode": self.mode,
            "page": page is not None,
            "extension_detected": self.icon_present(page) if page is not None else False,
            "icon_selector": ICON_SELECTOR,
            "play_selector": PLAY_SELECTOR,
        }

    # ---------------- the requested gesture ---------------- #

    def click_icon(self, page=None) -> bool:
        """Click Buster's in-widget icon (the one you'd click by hand)."""
        frame = _challenge_frame(page or self.page)
        if frame is None:
            log.debug("buster: no challenge frame yet — nothing to click")
            return False
        if not _wait_for(frame, ICON_SELECTOR, timeout=min(self.timeout, 10.0) * 1000):
            if not any(_count(frame, sel) for sel in ICON_FALLBACKS):
                log.debug("buster: icon never appeared (extension not installed?)")
                return False
        clicked = _click_first(frame, ICON_FALLBACKS, timeout=5000)
        if clicked:
            log.info("buster: clicked the icon (%s)", clicked)
            self.last_method = "extension"
        return bool(clicked)

    def click_play(self, page=None) -> bool:
        """Click the audio challenge's PLAY button."""
        frame = _challenge_frame(page or self.page)
        if frame is None:
            return False
        clicked = _click_first(frame, PLAY_FALLBACKS, timeout=5000)
        if clicked:
            log.info("buster: clicked PLAY (%s)", clicked)
            return True
        log.debug("buster: PLAY button not found")
        return False

    # ---------------- full solve ---------------- #

    def solve(self, page=None) -> BusterResult:
        """Solve whatever reCAPTCHA is on the page. Never raises."""
        page = page or self.page
        if page is None:
            return BusterResult(False, message="buster: no page attached")

        anchor = _anchor_frame(page)
        if anchor is None:
            return BusterResult(True, method="none", message="no reCAPTCHA on page")
        if anchor_checked(anchor):
            return BusterResult(True, method="none", message="already solved")

        if self.solve_checkbox:
            if not self._click_checkbox(anchor):
                return BusterResult(False, message="could not click the reCAPTCHA checkbox")
            if _poll(lambda: anchor_checked(anchor), timeout=min(self.timeout, 8.0),
                     interval=self.poll_interval):
                return BusterResult(True, method="checkbox", attempts=1,
                                    message="passed with the checkbox alone")

        for attempt in range(1, self.max_attempts + 1):
            log.info("buster: attempt %d/%d", attempt, self.max_attempts)
            method = self._attempt(page, anchor)
            if method:
                self.last_method = method
                return BusterResult(True, method=method, attempts=attempt,
                                    message=f"solved via {method}")
            self._fresh_challenge(page)
        return BusterResult(False, attempts=self.max_attempts,
                            message="buster could not solve the challenge")

    # ---------------- internals ---------------- #

    def _click_checkbox(self, anchor) -> bool:
        try:
            loc = anchor.locator(ANCHOR_CHECKBOX)
            if not loc.count():
                return False
            loc.first.click(timeout=8000)
            return True
        except Exception as exc:
            log.debug("buster: checkbox click failed: %s", exc)
            return False

    def _attempt(self, page, anchor) -> str:
        """One solving attempt. Returns 'extension'/'native' on success, else ''."""
        frame = _challenge_frame(page)
        if frame is None:
            # no challenge: either solved silently, or nothing to do
            return "checkbox" if anchor_checked(anchor) else ""

        use_extension = self.mode == "extension" or (
            self.mode == "auto" and self.icon_present(page)
        )
        if use_extension:
            if not self.click_icon(page):
                if self.mode == "extension":
                    return ""
                use_extension = False
            else:
                if _poll(lambda: anchor_checked(anchor), timeout=self.timeout,
                         interval=self.poll_interval):
                    log.info("buster: extension solved the challenge")
                    return "extension"
                log.info("buster: icon clicked but challenge still open — fallback")
                if self.mode == "extension":
                    return ""
                use_extension = False

        if use_extension:
            return ""
        if self._native(frame, anchor):
            return "native"
        return ""

    def _native(self, frame, anchor) -> bool:
        """Do precisely what Buster does, without the extension."""
        # 1. make sure the audio challenge is showing
        if not _count(frame, AUDIO_SRC):
            if _count(frame, AUDIO_TAB):
                _click(frame, AUDIO_TAB, timeout=5000)
            if not _wait_for(frame, AUDIO_SRC, timeout=8000):
                log.debug("buster-native: audio challenge never appeared")
                return False

        # 2. PLAY — the gesture the user asked for
        if self.simulate_play:
            self.click_play_frame(frame)

        # 3. read the MP3 the challenge is serving
        src = self._audio_src(frame)
        if not src:
            log.debug("buster-native: no audio source")
            return False

        # 4. transcribe
        try:
            answer = self._transcribe(src)
        except Exception as exc:
            log.warning("buster-native: transcription failed: %s", exc)
            return False
        if not answer:
            return False

        # 5. fill and verify
        if not self._fill(frame, answer):
            return False
        _click(frame, VERIFY_BUTTON, timeout=5000)
        if _poll(lambda: anchor_checked(anchor), timeout=min(self.timeout, 15.0),
                 interval=self.poll_interval):
            log.info("buster-native: challenge solved (%r)", answer)
            return True
        log.info("buster-native: answer rejected")
        return False

    def click_play_frame(self, frame) -> bool:
        clicked = _click_first(frame, PLAY_FALLBACKS, timeout=5000)
        if clicked:
            log.info("buster: clicked PLAY (%s)", clicked)
            return True
        return False

    def _audio_src(self, frame) -> str:
        for selector in (AUDIO_SRC, "audio", "audio source"):
            try:
                loc = frame.locator(selector)
                if not loc.count():
                    continue
                src = loc.first.get_attribute("src", timeout=5000)
                if src:
                    return src
            except Exception:
                continue
        return ""

    def _transcribe(self, audio_url: str) -> str:
        """Download + transcribe, reusing the existing audio pipeline."""
        from .recaptcha_solver import ensure_wav, transcribe_audio

        import requests

        log.info("buster: downloading challenge audio...")
        resp = requests.get(audio_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        import tempfile

        with tempfile.TemporaryDirectory(prefix="buster_") as tmp:
            mp3 = Path(tmp) / "audio.mp3"
            mp3.write_bytes(resp.content)
            wav = ensure_wav(mp3)
            return transcribe_audio(wav, language=self.language)

    def _fill(self, frame, answer: str) -> bool:
        try:
            box = frame.locator(ANSWER_INPUT)
            if not box.count():
                return False
            box.first.fill("", timeout=5000)
            box.first.press_sequentially(answer, delay=40)
            return True
        except Exception as exc:
            log.debug("buster: could not type the answer: %s", exc)
            return False

    def _fresh_challenge(self, page) -> None:
        frame = _challenge_frame(page)
        if frame is None:
            return
        if _click(frame, RELOAD_BUTTON, timeout=3000):
            time.sleep(1.0)


# --------------------------------------------------------------------------- #
# extension install helpers
# --------------------------------------------------------------------------- #

AMO_XPI_URL = (
    "https://addons.mozilla.org/firefox/downloads/latest/"
    "buster-captcha-solver/latest.xpi"
)


def buster_xpi_path(cfg=None) -> Path:
    raw = getattr(cfg, "extension_path", "") if cfg is not None else ""
    return Path(raw or "./profiles/buster/buster.xpi")


def extension_installed(cfg=None) -> bool:
    return buster_xpi_path(cfg).exists()


def download_extension(dest: Path | str | None = None, timeout: int = 120) -> Path:
    """Fetch Buster's signed .xpi from addons.mozilla.org (needs internet)."""
    import requests

    target = Path(dest) if dest else buster_xpi_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    log.info("Downloading Buster extension -> %s", target)
    resp = requests.get(AMO_XPI_URL, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    payload = resp.content
    if not payload.startswith(b"PK"):
        raise RuntimeError(
            "addons.mozilla.org did not return an .xpi (got %d bytes)"
            % len(payload)
        )
    target.write_bytes(payload)
    log.info("Saved %s (%d bytes)", target, len(payload))
    return target


__all__ = [
    "BusterSolver",
    "BusterResult",
    "ICON_SELECTOR",
    "PLAY_SELECTOR",
    "PLAY_FALLBACKS",
    "ICON_FALLBACKS",
    "AUDIO_SRC",
    "ANSWER_INPUT",
    "VERIFY_BUTTON",
    "AMO_XPI_URL",
    "buster_xpi_path",
    "extension_installed",
    "download_extension",
    "anchor_checked",
]
