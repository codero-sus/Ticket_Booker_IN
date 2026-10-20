"""Gemini captcha solving - on-device Gemini Nano + Gemini vision API.

Two transports, one solver:

1. GEMINI NANO (on-device, free, offline, zero API key)
   Chrome ships Gemini Nano behind the built-in Prompt API
   (``LanguageModel`` / ``self.ai.languageModel``). We drive it *through the
   booking page* so no extra process, network call, or key is involved.

   Nano's Prompt API is primarily TEXT-in. That makes it a superb
   OCR *repair* engine: Tesseract confuses 0/O, 1/l/I, S/5, B/8, Z/2, and
   Nano knows the IRCTC captcha shape well enough to fix those. Chrome's
   newer multimodal build also accepts images (``expectedInputs: [{type:
   "image"}]``); we attempt that first and fall back cleanly if the local
   build refuses.

2. GEMINI VISION (cloud, needs a key)
   Direct multimodal read of the captcha image. Set ``GEMINI_API_KEY`` or
   ``captcha.gemini.api_key``. Any Gemini model that accepts images works.

Both feed a consensus vote, and repairs are cached by perceptual-free hash so
repeated noise is fixed once, not re-asked. Pure standard library HTTP - no
new dependency. Fully offline-testable: every transport is a separate method.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from .base import BaseSolver, CaptchaError, CaptchaResult, clean_text

log = logging.getLogger("ticket_booker.captcha.gemini")

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-2.5-flash"
NANO_MODEL = "gemini-nano"

#: Confusable pairs IRCTC captchas love. Used by the local fallback repair.
CONFUSABLES = {
    "O": "0", "o": "0", "Q": "0", "D": "0",
    "l": "1", "I": "1", "i": "1", "|": "1",
    "S": "5", "s": "5",
    "B": "8", "Z": "2", "z": "2",
    "G": "6", "b": "6", "T": "7", "q": "9", "g": "9",
}

VISION_PROMPT = (
    "This image is a CAPTCHA. It contains 4 to 8 characters, mixing uppercase "
    "letters and digits. Read it exactly. Reply with ONLY those characters - "
    "no quotes, no spaces, no explanation. If you truly cannot read it, reply "
    "with the single word NONE."
)

REPAIR_PROMPT = (
    "A captcha OCR engine read the text {text!r}. IRCTC captchas are 4 to 8 "
    "alphanumeric characters. OCR often confuses 0/O/Q, 1/l/I, 5/S, 8/B, 2/Z, "
    "6/G. Reply with ONLY the most likely correct captcha text, nothing else. "
    "If the reading is already plausible, repeat it unchanged."
)

_NANO_JS = r"""
async (payload) => {
  const LM = (self.LanguageModel && self.LanguageModel.create)
      ? self.LanguageModel
      : (self.ai && self.ai.languageModel) ? self.ai.languageModel : null;
  if (!LM) {
    return {ok: false, reason: "no Prompt API (need Chrome 138+ with Gemini Nano enabled)"};
  }
  let avail = "readily";
  try {
    if (LM.availability) avail = await LM.availability();
  } catch (e) { /* older builds */ }
  if (avail === "no" || avail === "unavailable") {
    return {ok: false, reason: "Gemini Nano model not available on this device"};
  }
  const wantsImage = !!payload.image;
  const opts = {
    expectedInputs: wantsImage
      ? [{type: "image"}]
      : [{type: "text", languages: ["en"]}],
    expectedOutputs: [{type: "text", languages: ["en"]}]
  };
  let session;
  try {
    session = await LM.create(opts);
  } catch (e) {
    if (wantsImage) {
      return {ok: false, reason: "multimodal unavailable: " + e.message, nomultimodal: true};
    }
    return {ok: false, reason: "create failed: " + e.message};
  }
  try {
    let msg;
    if (wantsImage) {
      const bin = atob(payload.image);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const blob = new Blob([bytes], {type: payload.mime || "image/png"});
      msg = [
        {type: "text", value: payload.prompt},
        {type: "image", value: blob}
      ];
    } else {
      msg = payload.prompt;
    }
    const out = await session.prompt(msg);
    return {ok: true, text: String(out)};
  } catch (e) {
    return {ok: false, reason: "prompt failed: " + e.message};
  } finally {
    try { session.destroy(); } catch (e) { /* ignore */ }
  }
}
"""


def _mime_of(image_bytes: bytes) -> str:
    head = image_bytes[:12]
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if head.startswith(b"GIF8"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"BM"):
        return "image/bmp"
    return "image/png"


def _best_token(text: str, max_chars: int) -> str:
    """Pick the most captcha-shaped token from a chatty model reply.

    Scores digits and mixed case highest, so "aB3d" beats the word "captcha"
    in "The captcha reads aB3d". Ties go to the later token (models answer last).
    """
    tokens = [t for t in re.findall(r"[A-Za-z0-9]+", text) if 3 <= len(t) <= max_chars]
    if not tokens:
        return ""
    best, best_score = "", -1.0
    for pos, tok in enumerate(tokens):
        score = 0.0
        if any(ch.isdigit() for ch in tok):
            score += 2.0
        if any(ch.isupper() for ch in tok) and any(ch.islower() for ch in tok):
            score += 1.0
        if tok.isupper() and 4 <= len(tok) <= max_chars:
            score += 0.5
        score += 0.01 * pos  # later tokens win ties
        if score > best_score:
            best, best_score = tok, score
    return best


def normalize_answer(raw: str, max_chars: int = 8) -> str:
    """Turn any model reply into a clean captcha string (or '')."""
    text = str(raw or "").strip()
    if not text:
        return ""
    # strip markdown fences, quotes, labels like "CAPTCHA:" / "Answer:"
    text = re.sub(r"```[a-zA-Z]*", " ", text).replace("`", " ")
    text = re.sub(r"^\s*(captcha|answer|text|result)\s*[:\-]\s*", " ", text, flags=re.I)
    if re.fullmatch(r"\s*none\s*", text, flags=re.I):
        return ""
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    if len(cleaned) > max_chars:
        # a chatty model emits a sentence; keep the most captcha-shaped token
        return _best_token(text, max_chars) or cleaned[:max_chars]
    return cleaned


def vote_answers(readings: list[tuple[str, float]]) -> tuple[str, float] | None:
    """Consensus vote: majority wins, confidence breaks ties."""
    buckets: dict[str, list[float]] = {}
    for text, conf in readings:
        key = (text or "").strip()
        if key:
            buckets.setdefault(key, []).append(float(conf))
    if not buckets:
        return None
    scored = [
        (text, max(confs) + 10.0 * (len(confs) - 1), sum(confs) / len(confs))
        for text, confs in buckets.items()
    ]
    scored.sort(key=lambda item: (item[1], item[2]), reverse=True)
    return scored[0][0], round(scored[0][2], 1)


class GeminiSolver(BaseSolver):
    """Gemini Nano (on-device) + Gemini vision (cloud) captcha solver."""

    name = "gemini"

    def __init__(
        self,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        mode: str = "auto",
        timeout: float = 25.0,
        max_variants: int = 2,
        repair_ocr: bool = True,
        temperature: float = 0.0,
        cache_path: str | Path | None = "./profiles/captcha_cache.json",
        page=None,
    ) -> None:
        self.api_key = (api_key or os.environ.get("GEMINI_API_KEY", "") or "").strip()
        self.model = (model or DEFAULT_MODEL).strip()
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.mode = (mode or "auto").lower()
        self.timeout = float(timeout)
        self.max_variants = max(1, int(max_variants))
        self.repair_ocr = bool(repair_ocr)
        self.temperature = float(temperature)
        self.cache_path = Path(cache_path) if cache_path else None
        self.page = page
        self._cache: dict[str, str] | None = None
        self._nano_reason = "no page attached"

    # ------------------------------------------------------------------ #
    # page / availability
    # ------------------------------------------------------------------ #

    def set_page(self, page) -> None:
        """Attach the live browser page so Gemini Nano can be driven in-place."""
        self.page = page

    attach_page = set_page

    @property
    def nano_ready(self) -> bool:
        return self.page is not None and self.mode in ("auto", "nano")

    @property
    def api_ready(self) -> bool:
        return bool(self.api_key) and self.mode in ("auto", "api")

    def available(self) -> bool:
        if self.api_ready:
            return True
        if self.nano_ready:
            return True
        if self.mode == "nano":
            self._nano_reason = "no page attached (Nano runs inside the browser)"
        elif not self.api_key:
            self._nano_reason = (
                "no GEMINI_API_KEY and no page attached for on-device Gemini Nano"
            )
        return False

    def availability_reason(self) -> str:
        if self.available():
            return ""
        return f"gemini: {self._nano_reason}"

    def status(self) -> dict:
        """Human/doctor friendly summary of both transports."""
        return {
            "solver": self.name,
            "mode": self.mode,
            "api": {
                "ready": self.api_ready,
                "model": self.model,
                "reason": "" if self.api_key else "no api key ($GEMINI_API_KEY)",
            },
            "nano": {
                "ready": self.nano_ready,
                "model": NANO_MODEL,
                "reason": "" if self.page is not None else "no page attached",
            },
            "repair_ocr": self.repair_ocr,
            "cached_repairs": len(self._load_cache()),
        }

    # ------------------------------------------------------------------ #
    # transport 1: cloud vision
    # ------------------------------------------------------------------ #

    def _ask_api(self, image_bytes: bytes, prompt: str = VISION_PROMPT) -> str:
        """One multimodal request. Returns the raw model text ('' on failure)."""
        if not self.api_key:
            raise CaptchaError("gemini: no API key")
        url = f"{self.base_url}/models/{self.model}:generateContent"
        body = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {
                        "mime_type": _mime_of(image_bytes),
                        "data": base64.b64encode(image_bytes).decode("ascii"),
                    }},
                ]
            }],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": 32,
                "candidateCount": 1,
            },
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            raise CaptchaError(f"gemini http {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise CaptchaError(f"gemini network error: {exc.reason}") from exc
        except (TimeoutError, OSError) as exc:
            raise CaptchaError(f"gemini request failed: {exc}") from exc
        return self._extract_text(payload)

    @staticmethod
    def _extract_text(payload: dict) -> str:
        try:
            cands = payload.get("candidates") or []
            if not cands:
                return ""
            parts = (cands[0].get("content") or {}).get("parts") or []
            chunks = [p.get("text", "") for p in parts if isinstance(p, dict)]
            return "".join(chunks).strip()
        except Exception:
            return ""

    # ------------------------------------------------------------------ #
    # transport 2: on-device Gemini Nano (inside the browser)
    # ------------------------------------------------------------------ #

    def _ask_nano(self, prompt: str, image_bytes: bytes | None = None) -> str:
        """Run a prompt through Chrome's built-in Gemini Nano. '' if unavailable."""
        if self.page is None:
            raise CaptchaError("gemini-nano: no page attached")
        payload = {"prompt": prompt}
        if image_bytes is not None:
            payload["image"] = base64.b64encode(image_bytes).decode("ascii")
            payload["mime"] = _mime_of(image_bytes)
        try:
            out = self.page.evaluate(_NANO_JS, payload)
        except Exception as exc:
            raise CaptchaError(f"gemini-nano: page.evaluate failed: {exc}") from exc
        if not isinstance(out, dict):
            raise CaptchaError(f"gemini-nano: unexpected reply {out!r}")
        if not out.get("ok"):
            self._nano_reason = str(out.get("reason") or "nano unavailable")
            raise CaptchaError(f"gemini-nano: {self._nano_reason}")
        return str(out.get("text") or "")

    # ------------------------------------------------------------------ #
    # repair cache (OCR text -> corrected text)
    # ------------------------------------------------------------------ #

    def _load_cache(self) -> dict[str, str]:
        if self._cache is not None:
            return self._cache
        data: dict[str, str] = {}
        if self.cache_path is not None:
            try:
                if self.cache_path.exists():
                    loaded = json.loads(self.cache_path.read_text(encoding="utf-8") or "{}")
                    if isinstance(loaded, dict):
                        data = {str(k): str(v) for k, v in loaded.items()}
            except Exception as exc:
                log.debug("captcha cache unreadable (%s) - starting fresh", exc)
        self._cache = data
        return data

    def _save_cache(self) -> None:
        if self.cache_path is None or self._cache is None:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.cache_path.parent), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._cache, fh, indent=1, sort_keys=True)
            os.replace(tmp, self.cache_path)
        except Exception as exc:
            log.debug("captcha cache not saved: %s", exc)

    @staticmethod
    def _cache_key(text: str) -> str:
        return hashlib.sha256(f"repair|{text}".encode("utf-8")).hexdigest()[:20]

    def polish(self, text: str) -> str:
        """Repair an OCR reading with Gemini Nano (cached). Returns '' if no help."""
        original = clean_text(str(text or ""))
        if not original or not self.repair_ocr:
            return ""
        cache = self._load_cache()
        key = self._cache_key(original)
        if key in cache:
            log.debug("nano repair cache hit for %r -> %r", original, cache[key])
            return cache[key]
        if not self.nano_ready:
            return ""
        try:
            raw = self._ask_nano(REPAIR_PROMPT.format(text=original))
        except CaptchaError as exc:
            log.debug("nano repair unavailable: %s", exc)
            return ""
        fixed = normalize_answer(raw)
        if not fixed or fixed == original:
            return ""
        cache[key] = fixed
        self._save_cache()
        log.info("Gemini Nano repaired %r -> %r", original, fixed)
        return fixed

    # ------------------------------------------------------------------ #
    # the brute path
    # ------------------------------------------------------------------ #

    def solve_image(self, image_bytes: bytes) -> CaptchaResult:
        if not self.available():
            raise CaptchaError(self.availability_reason())

        readings: list[tuple[str, float]] = []

        # 1. cloud vision across N preprocessing variants
        if self.api_ready:
            for attempt in range(self.max_variants):
                blob = image_bytes
                if attempt:
                    try:
                        blob = self._variant(image_bytes, attempt)
                    except Exception as exc:
                        log.debug("gemini variant %d skipped: %s", attempt, exc)
                        continue
                try:
                    text = normalize_answer(self._ask_api(blob))
                except CaptchaError as exc:
                    log.warning("gemini api attempt %d: %s", attempt + 1, exc)
                    continue
                if text:
                    readings.append((text, 90.0))
                    log.debug("gemini api read %r", text)

        # 2. on-device Nano vision (works only on multimodal Chrome builds)
        if self.nano_ready:
            try:
                text = normalize_answer(
                    self._ask_nano(VISION_PROMPT, image_bytes=image_bytes)
                )
                if text:
                    readings.append((text, 80.0))
                    log.debug("gemini nano read %r", text)
            except CaptchaError as exc:
                log.debug("nano vision skipped: %s", exc)

        voted = vote_answers(readings)
        if voted is None:
            return CaptchaResult(solver=self.name)

        text, conf = voted
        # low-agreement answers get a Nano polish pass
        if len(readings) > 1 and text and self.nano_ready:
            fixed = self.polish(text)
            if fixed:
                text, conf = fixed, max(conf, 70.0)
        log.info("gemini solved captcha: %r (conf=%.1f from %d readings)",
                 text, conf, len(readings))
        return CaptchaResult(text=text, confidence=conf, solver=self.name)

    @staticmethod
    def _variant(image_bytes: bytes, index: int) -> bytes:
        """Upscale + autocontrast a copy of the captcha to give the model a 2nd look."""
        import io

        from PIL import Image, ImageOps

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        if index % 2 == 1:
            img = ImageOps.autocontrast(img)
        factor = 2 + (index % 2)
        img = img.resize((img.width * factor, img.height * factor), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


__all__ = [
    "GeminiSolver",
    "NANO_MODEL",
    "DEFAULT_MODEL",
    "VISION_PROMPT",
    "REPAIR_PROMPT",
    "normalize_answer",
    "vote_answers",
    "CONFUSABLES",
    "_best_token",
]
