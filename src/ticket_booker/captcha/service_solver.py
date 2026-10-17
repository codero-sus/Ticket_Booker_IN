"""Paid captcha-service fallback (2Captcha / AntiCaptcha image-to-text).

Only used when local OCR fails (or is disabled) AND the service is enabled
with an API key. Key comes from config or $CAPTCHA_API_KEY.
Pricing is typically ~$0.50-3 per 1000 image captchas.
"""

from __future__ import annotations

import base64
import logging
import time

from .base import BaseSolver, CaptchaError, CaptchaResult, clean_text

log = logging.getLogger("ticket_booker.captcha.service")


class TwoCaptchaSolver(BaseSolver):
    """2Captcha (2captcha.com) standard image captcha API."""

    name = "2captcha"
    IN_URL = "https://api.2captcha.com/in.php"
    RES_URL = "https://api.2captcha.com/res.php"

    def __init__(self, api_key: str = "", poll_timeout: int = 120) -> None:
        self.api_key = api_key.strip()
        self.poll_timeout = poll_timeout

    def available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import requests  # noqa: F401
        except ImportError:
            return False
        return True

    def availability_reason(self) -> str:
        if not self.api_key:
            return "2captcha: no API key (set captcha.service.api_key or $CAPTCHA_API_KEY)"
        try:
            import requests  # noqa: F401
        except ImportError:
            return "2captcha: `requests` not installed"
        return ""

    def solve_image(self, image_bytes: bytes) -> CaptchaResult:
        import requests

        if not self.available():
            raise CaptchaError(self.availability_reason())
        b64 = base64.b64encode(image_bytes).decode()
        r = requests.post(
            self.IN_URL,
            data={"key": self.api_key, "method": "base64", "body": b64,
                  "json": 1, "phrase": 0, "regsense": 0},
            timeout=30,
        ).json()
        if r.get("status") != 1:
            raise CaptchaError(f"2captcha submit failed: {r}")
        captcha_id = r["request"]
        log.info("2captcha job %s submitted, polling...", captcha_id)
        deadline = time.time() + self.poll_timeout
        while time.time() < deadline:
            time.sleep(5)
            g = requests.get(
                self.RES_URL,
                params={"key": self.api_key, "action": "get",
                        "id": captcha_id, "json": 1},
                timeout=30,
            ).json()
            if g.get("status") == 1:
                text = clean_text(str(g["request"]))
                log.info("2captcha solved: %r", text)
                return CaptchaResult(text=text, confidence=95.0, solver=self.name)
            if g.get("request") != "CAPCHA_NOT_READY":
                raise CaptchaError(f"2captcha error: {g}")
        raise CaptchaError("2captcha timed out.")


class AntiCaptchaSolver(BaseSolver):
    """AntiCaptcha (anti-captcha.com) ImageToTextTask API."""

    name = "anticaptcha"
    API = "https://api.anti-captcha.com"

    def __init__(self, api_key: str = "", poll_timeout: int = 120) -> None:
        self.api_key = api_key.strip()
        self.poll_timeout = poll_timeout

    def available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import requests  # noqa: F401
        except ImportError:
            return False
        return True

    def availability_reason(self) -> str:
        if not self.api_key:
            return "anticaptcha: no API key (set captcha.service.api_key or $CAPTCHA_API_KEY)"
        try:
            import requests  # noqa: F401
        except ImportError:
            return "anticaptcha: `requests` not installed"
        return ""

    def solve_image(self, image_bytes: bytes) -> CaptchaResult:
        import requests

        if not self.available():
            raise CaptchaError(self.availability_reason())
        b64 = base64.b64encode(image_bytes).decode()
        r = requests.post(
            f"{self.API}/createTask",
            json={"clientKey": self.api_key,
                  "task": {"type": "ImageToTextTask", "body": b64}},
            timeout=30,
        ).json()
        if r.get("errorId"):
            raise CaptchaError(f"anticaptcha submit failed: {r}")
        task_id = r["taskId"]
        log.info("anticaptcha task %s submitted, polling...", task_id)
        deadline = time.time() + self.poll_timeout
        while time.time() < deadline:
            time.sleep(5)
            g = requests.post(
                f"{self.API}/getTaskResult",
                json={"clientKey": self.api_key, "taskId": task_id},
                timeout=30,
            ).json()
            if g.get("errorId"):
                raise CaptchaError(f"anticaptcha error: {g}")
            if g.get("status") == "ready":
                text = clean_text(str(g["solution"]["text"]))
                log.info("anticaptcha solved: %r", text)
                return CaptchaResult(text=text, confidence=95.0, solver=self.name)
        raise CaptchaError("anticaptcha timed out.")


ServiceSolver = TwoCaptchaSolver  # backwards-friendly alias
