"""Offline tests for Gemini captcha solving (Nano on-device + cloud vision)."""

import io
import json
import urllib.error
import urllib.request

import pytest

from ticket_booker.captcha.base import CaptchaResult
from ticket_booker.captcha.gemini_solver import (
    GeminiSolver,
    normalize_answer,
    vote_answers,
)
from ticket_booker.god.infinite import OmniSolver


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

class FakePage:
    """Stand-in for a Playwright page running Chrome's Prompt API."""

    def __init__(self, reply="ABCD", ok=True, raise_on_eval=False):
        self.reply = reply
        self.ok = ok
        self.raise_on_eval = raise_on_eval
        self.calls: list[dict] = []

    def evaluate(self, script, payload=None):
        self.calls.append(payload or {})
        if self.raise_on_eval:
            raise RuntimeError("page crashed")
        if self.ok:
            return {"ok": True, "text": self.reply}
        return {"ok": False, "reason": "Gemini Nano model not available"}


class FakeSolver:
    name = "fake-ocr"

    def __init__(self, text="", conf=0.0, available=True):
        self.text = text
        self.conf = conf
        self._available = available

    def available(self):
        return self._available

    def solve_image(self, image_bytes):
        return CaptchaResult(text=self.text, confidence=self.conf, solver=self.name)


def png_bytes(width=40, height=20, color="white"):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def api_payload(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


# --------------------------------------------------------------------------- #
# answer normalization / voting
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw,expected", [
    ("ABCD", "ABCD"),
    ("  ab12  ", "ab12"),
    ('"aB3d"', "aB3d"),
    ("```text\naB3d\n```", "aB3d"),
    ("CAPTCHA: aB3d", "aB3d"),
    ("Answer: aB3d", "aB3d"),
    ("NONE", ""),
    ("none", ""),
    ("", ""),
    ("The captcha reads aB3d", "aB3d"),  # chatty model -> longest token
    ("aB3d!", "aB3d"),
])
def test_normalize_answer(raw, expected):
    assert normalize_answer(raw) == expected


def test_normalize_answer_truncates_runaway():
    out = normalize_answer("ABCDEFGHIJKLMNOP")
    assert len(out) <= 8


def test_vote_majority_wins():
    assert vote_answers([("ABCD", 90), ("ABCD", 80), ("ABCE", 99)])[0] == "ABCD"


def test_vote_confidence_breaks_ties():
    assert vote_answers([("AAAA", 95), ("BBBB", 80)])[0] == "AAAA"


def test_vote_empty():
    assert vote_answers([]) is None
    assert vote_answers([("", 90)]) is None


# --------------------------------------------------------------------------- #
# availability matrix
# --------------------------------------------------------------------------- #

def test_unavailable_without_key_or_page(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    g = GeminiSolver(api_key="", page=None)
    assert g.available() is False
    assert "GEMINI_API_KEY" in g.availability_reason()
    assert g.status()["api"]["ready"] is False


def test_api_ready_with_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    g = GeminiSolver(api_key="k-123")
    assert g.available() is True
    assert g.api_ready is True
    assert g.status()["api"]["ready"] is True


def test_key_from_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    g = GeminiSolver()
    assert g.api_key == "env-key" and g.available() is True


def test_nano_ready_only_with_page(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    g = GeminiSolver(api_key="", mode="nano")
    assert g.available() is False
    g.set_page(FakePage())
    assert g.available() is True
    assert g.status()["nano"]["ready"] is True


def test_api_mode_ignores_page(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    g = GeminiSolver(api_key="", mode="api", page=FakePage())
    assert g.available() is False


# --------------------------------------------------------------------------- #
# cloud vision transport (HTTP mocked)
# --------------------------------------------------------------------------- #

def _install_urlopen(monkeypatch, handler):
    monkeypatch.setattr(urllib.request, "urlopen", handler)


def test_ask_api_builds_request_and_parses(monkeypatch):
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(api_payload("aB3d")).encode()

    def handler(req, timeout=None):
        seen["url"] = req.full_url
        seen["headers"] = dict(req.header_items())
        seen["body"] = json.loads(req.data.decode())
        seen["timeout"] = timeout
        return Resp()

    _install_urlopen(monkeypatch, handler)
    g = GeminiSolver(api_key="k-123", model="gemini-2.5-flash")
    out = g._ask_api(png_bytes())

    assert out == "aB3d"
    assert "gemini-2.5-flash:generateContent" in seen["url"]
    assert seen["headers"].get("X-goog-api-key") == "k-123"
    parts = seen["body"]["contents"][0]["parts"]
    assert parts[0]["text"].startswith("This image is a CAPTCHA")
    assert parts[1]["inline_data"]["mime_type"] == "image/png"
    assert seen["body"]["generationConfig"]["temperature"] == 0.0


def test_ask_api_http_error_raises(monkeypatch):
    from ticket_booker.captcha.base import CaptchaError

    def handler(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 429, "rate limited", None, io.BytesIO(b'{"error":"quota"}'))

    _install_urlopen(monkeypatch, handler)
    g = GeminiSolver(api_key="k-123")
    with pytest.raises(CaptchaError) as exc:
        g._ask_api(png_bytes())
    assert "429" in str(exc.value)


def test_ask_api_network_error_raises(monkeypatch):
    from ticket_booker.captcha.base import CaptchaError

    def handler(req, timeout=None):
        raise urllib.error.URLError("no route to host")

    _install_urlopen(monkeypatch, handler)
    g = GeminiSolver(api_key="k-123")
    with pytest.raises(CaptchaError):
        g._ask_api(png_bytes())


def test_extract_text_tolerates_junk():
    assert GeminiSolver._extract_text({}) == ""
    assert GeminiSolver._extract_text({"candidates": []}) == ""
    assert GeminiSolver._extract_text({"candidates": [{"content": {"parts": [
        {"text": "aB"}, {"text": "3d"}]}}]}) == "aB3d"


# --------------------------------------------------------------------------- #
# solve_image across transports
# --------------------------------------------------------------------------- #

def test_solve_image_uses_api(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    g = GeminiSolver(api_key="k", max_variants=1)
    monkeypatch.setattr(g, "_ask_api", lambda blob, prompt=None: "aB3d")
    res = g.solve_image(png_bytes())
    assert res.ok and res.text == "aB3d" and res.solver == "gemini"


def test_solve_image_votes_across_variants(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    g = GeminiSolver(api_key="k", max_variants=3)
    reads = iter(["aB3d", "aB3d", "aB3e"])
    monkeypatch.setattr(g, "_variant", lambda blob, i: blob)
    monkeypatch.setattr(g, "_ask_api", lambda blob, prompt=None: next(reads))
    res = g.solve_image(png_bytes())
    assert res.text == "aB3d"


def test_solve_image_falls_back_to_nano_vision(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    page = FakePage(reply="zz99")
    g = GeminiSolver(api_key="", mode="nano", page=page)
    res = g.solve_image(png_bytes())
    assert res.ok and res.text == "zz99"
    assert page.calls and page.calls[0]["image"]  # image bytes were shipped


def test_solve_image_no_readings_returns_empty(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    g = GeminiSolver(api_key="", mode="nano", page=FakePage(ok=False))
    res = g.solve_image(png_bytes())
    assert res.ok is False and res.text == ""


def test_solve_image_unavailable_raises(monkeypatch):
    from ticket_booker.captcha.base import CaptchaError

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(CaptchaError):
        GeminiSolver(api_key="").solve_image(png_bytes())


# --------------------------------------------------------------------------- #
# Nano OCR repair + cache
# --------------------------------------------------------------------------- #

def test_nano_repairs_ocr(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    page = FakePage(reply="aB3d")
    g = GeminiSolver(api_key="", mode="nano", page=page,
                     cache_path=tmp_path / "cache.json")
    assert g.polish("aB3O") == "aB3d"
    assert page.calls and "aB3O" in page.calls[0]["prompt"]


def test_nano_repair_is_cached(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    page = FakePage(reply="aB3d")
    cache = tmp_path / "cache.json"
    g = GeminiSolver(api_key="", mode="nano", page=page, cache_path=cache)

    assert g.polish("aB3O") == "aB3d"
    calls_after_first = len(page.calls)
    assert g.polish("aB3O") == "aB3d"  # served from disk cache
    assert len(page.calls) == calls_after_first
    assert cache.exists()
    assert json.loads(cache.read_text())

    again = GeminiSolver(api_key="", mode="nano", page=FakePage(reply="XXXX"),
                         cache_path=cache)
    assert again.polish("aB3O") == "aB3d"  # cache survives a new process


def test_nano_repair_noop_when_unchanged(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    g = GeminiSolver(api_key="", mode="nano", page=FakePage(reply="aB3O"),
                     cache_path=tmp_path / "c.json")
    assert g.polish("aB3O") == ""  # nothing to change -> no override


def test_polish_disabled(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    g = GeminiSolver(api_key="", mode="nano", page=FakePage(reply="aB3d"),
                     repair_ocr=False, cache_path=tmp_path / "c.json")
    assert g.polish("aB3O") == ""


def test_polish_survives_page_explosion(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    g = GeminiSolver(api_key="", mode="nano", page=FakePage(raise_on_eval=True),
                     cache_path=tmp_path / "c.json")
    assert g.polish("aB3O") == ""


# --------------------------------------------------------------------------- #
# manager wiring
# --------------------------------------------------------------------------- #

def test_manager_puts_gemini_first():
    from ticket_booker.captcha.manager import AutoCaptcha
    from ticket_booker.config import CaptchaCfg

    ac = AutoCaptcha(CaptchaCfg())
    assert ac.solvers[0].name == "gemini"
    assert ac.gemini is not None


def test_manager_honours_disable():
    from ticket_booker.captcha.manager import AutoCaptcha
    from ticket_booker.config import CaptchaCfg

    cfg = CaptchaCfg()
    cfg.gemini.enabled = False
    ac = AutoCaptcha(cfg)
    assert all(s.name != "gemini" for s in ac.solvers)
    assert ac.gemini is None


def test_manager_attaches_page_to_nano(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from ticket_booker.captcha.manager import AutoCaptcha
    from ticket_booker.config import CaptchaCfg

    ac = AutoCaptcha(CaptchaCfg())
    assert ac.nano_pending is True
    page = FakePage(reply="aB3d")
    ac.attach_page(page)
    assert ac.gemini.page is page
    res = ac.solve_text_image(png_bytes())
    assert res.text == "aB3d"


def test_manager_polishes_weak_ocr(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from ticket_booker.captcha.manager import AutoCaptcha
    from ticket_booker.config import CaptchaCfg

    cfg = CaptchaCfg(mode="auto")
    cfg.gemini.cache = str(tmp_path / "c.json")
    ac = AutoCaptcha(cfg)
    ac.gemini.set_page(FakePage(reply="aB3d"))
    ac.solvers = [FakeSolver(text="aB3O", conf=20.0)]  # weak OCR reading
    res = ac.solve_text_image(png_bytes())
    assert res.text == "aB3d"
    assert res.solver == "fake-ocr+nano"


def test_manager_keeps_confident_ocr(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from ticket_booker.captcha.manager import AutoCaptcha
    from ticket_booker.config import CaptchaCfg

    ac = AutoCaptcha(CaptchaCfg())
    ac.gemini.set_page(FakePage(reply="WRONG"))
    ac.solvers = [FakeSolver(text="aB3O", conf=95.0)]
    res = ac.solve_text_image(png_bytes())
    assert res.text == "aB3O" and res.solver == "fake-ocr"


def test_manager_manual_mode_short_circuits():
    from ticket_booker.captcha.manager import AutoCaptcha
    from ticket_booker.config import CaptchaCfg

    ac = AutoCaptcha(CaptchaCfg(mode="manual"))
    res = ac.solve_text_image(b"whatever")
    assert res.solver == "manual" and not res.ok


# --------------------------------------------------------------------------- #
# omni solver picks Nano up late (page attaches after construction)
# --------------------------------------------------------------------------- #

def test_omni_sees_late_available_solver(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    g = GeminiSolver(api_key="", mode="nano")
    omni = OmniSolver([g], timeout=5.0)
    assert omni.live() == []          # constructed before the page existed
    g.set_page(FakePage(reply="q7w2"))
    assert [s.name for s in omni.live()] == ["gemini"]
    res = omni.solve_text_image(png_bytes())
    assert res.text == "q7w2"


# --------------------------------------------------------------------------- #
# config + doctor + preflight wiring
# --------------------------------------------------------------------------- #

def test_config_env_key_and_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    from ticket_booker.config import load_config
    from ticket_booker.config import CaptchaCfg

    assert CaptchaCfg().gemini.enabled is True
    cfg_file = tmp_path / "c.json"
    cfg_file.write_text(json.dumps({
        "irctc": {"username": "u", "password": "p", "mobile": "9999999999"},
        "journey": {"from_station": "NDLS", "to_station": "BCT", "date": "2030-01-01"},
        "passengers": [{"name": "Test User", "age": 30, "gender": "M", "berth": "LB"}],
        "captcha": {"gemini": {"mode": "nano", "model": "gemini-2.5-flash-lite"}},
    }), encoding="utf-8")
    cfg = load_config(str(cfg_file))
    assert cfg.captcha.gemini.api_key == "from-env"
    assert cfg.captcha.gemini.mode == "nano"
    assert cfg.captcha.gemini.model == "gemini-2.5-flash-lite"


def test_preflight_counts_gemini(tmp_path):
    from ticket_booker.config import load_config
    from ticket_booker.god.preflight import preflight

    cfg_file = tmp_path / "c.json"
    cfg_file.write_text(json.dumps({
        "irctc": {"username": "u", "password": "p", "mobile": "9999999999"},
        "journey": {"from_station": "NDLS", "to_station": "BCT", "date": "2030-01-01"},
        "passengers": [{"name": "Test User", "age": 30, "gender": "M", "berth": "LB"}],
        "captcha": {"gemini": {"enabled": True}},
    }), encoding="utf-8")
    res = preflight(load_config(str(cfg_file)))
    check = next(c for c in res.checks if c["name"] == "captcha.solvers")
    assert "gemini=" in check["msg"]
    assert check["ok"] is True


def test_example_config_documents_gemini():
    from pathlib import Path

    data = json.loads(
        (Path(__file__).resolve().parents[1] / "config.example.json").read_text(encoding="utf-8"))
    assert "gemini" in data["captcha"]
    assert data["captcha"]["gemini"]["repair_ocr"] is True
