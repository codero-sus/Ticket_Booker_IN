"""Offline GOD tests — signals, memory, diagnostics, engine (no browser)."""

import json
from pathlib import Path

from ticket_booker.god.diagnostics import redact_config, redact_text, save_bundle
from ticket_booker.god.engine import ROUNDS, god_run
from ticket_booker.god.memory import SelectorMemory
from ticket_booker.god.signals import (
    best_match,
    detect_block,
    detect_session_dead,
    escalate_delay,
    looks_like_browser_death,
    normalize,
)
from ticket_booker.tools.base import BlockedError

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.json"


def _cfg(level: int = 4, proxies=None):
    from ticket_booker.config import load_config

    cfg = load_config(EXAMPLE)
    cfg.brute.level = level
    if proxies is not None:
        cfg.brute.proxy_list = proxies
    return cfg


# ---------- signals ----------

def test_normalize():
    assert normalize("  SUBMIT »\n") == "submit"
    assert normalize("Get-Status!") == "get status"


def test_best_match_exact_and_fuzzy():
    assert best_match("Submit", ["Cancel", "Submit"])[0] == "Submit"
    hit = best_match("Submitt", ["Cancel", "Submit"], cutoff=0.6)
    assert hit and hit[0] == "Submit"
    assert best_match("zzzqqq", ["Cancel", "Submit"], cutoff=0.8) is None
    assert best_match("", ["Submit"]) is None


def test_detect_block():
    assert detect_block("Error 403 Forbidden — Access Denied") == "access denied"
    assert detect_block("Access Denied by server") is not None
    assert detect_block("Just a moment... checking browser") is not None
    assert detect_block("Welcome to IRCTC, search trains") is None
    assert detect_block("") is None


def test_detect_session_dead():
    assert detect_session_dead("Your session expired, please login again") is True
    assert detect_session_dead("Trains from NDLS to CNB") is False


def test_escalate_delay_bounds():
    assert 0 < escalate_delay(1, base=2.0, cap=100) < 10
    assert escalate_delay(6, base=2.0, cap=100) > 20
    assert escalate_delay(99, base=2.0, cap=25.0) <= 25.0 * 1.31


def test_browser_death_detector():
    assert looks_like_browser_death(Exception("Target closed unexpectedly")) is True
    assert looks_like_browser_death(Exception("Browser has been closed")) is True
    assert looks_like_browser_death(ValueError("No trains found")) is False
    assert looks_like_browser_death("plain string crash") is True


def test_rounds_table_sane():
    assert ROUNDS[1] == 1 and ROUNDS[5] >= ROUNDS[4] >= ROUNDS[3] >= 1


# ---------- memory ----------

def test_memory_roundtrip(tmp_path):
    m = SelectorMemory(tmp_path / "mem.json")
    assert m.preferred("click:submit") is None
    m.record("click:submit", "xpath")
    m.record("click:submit", "text")
    m.record("click:submit", "text")
    assert m.preferred("click:submit") == "text"
    assert m.order("click:submit", ["xpath", "text", "filter"])[0] == "text"
    # persists across instances
    m2 = SelectorMemory(tmp_path / "mem.json")
    assert m2.preferred("click:submit") == "text"


def test_memory_tolerates_garbage(tmp_path):
    p = tmp_path / "mem.json"
    p.write_text("{not json", encoding="utf-8")
    m = SelectorMemory(p)
    assert m.preferred("x") is None
    m.record("x", "y")  # still works, heals file
    assert m.preferred("x") == "y"


# ---------- diagnostics ----------

def test_redact_text():
    blob = '{"password": "hunter2", "api_key": "ABC123", "upi_id": "a@upi", "ok": 1}'
    out = redact_text(blob)
    assert "hunter2" not in out and "ABC123" not in out and "a@upi" not in out
    assert '"ok": 1' in out
    assert redact_text("card 4111 1111 1111 1111 here").count("4111") == 0
    assert redact_text("") == ""


def test_redact_config_dict():
    out = redact_config({"password": "x", "nested": {"token": "y"}, "safe": 1})
    s = json.dumps(out)
    assert '"x"' not in s and '"y"' not in s and '"safe": 1' in s


class _FakePage:
    url = "https://example.test/fail?x=1"

    def screenshot(self, path=None, full_page=False):
        if path:
            Path(path).write_bytes(b"FAKEPNG")
        return b"FAKEPNG"

    def content(self):
        return "<html>oops {'password': 'shh'}</html>"


def test_save_bundle(tmp_path):
    out = save_bundle(tmp_path, "unit FAILED", page=_FakePage(),
                      extra={"error": "boom", "config": {"password": "shh"}})
    assert (out / "screenshot.png").exists()
    assert (out / "page.html").exists()
    assert "example.test" in (out / "url.txt").read_text()
    extra = (out / "extra.json").read_text()
    assert "boom" in extra and "shh" not in extra


def test_save_bundle_never_raises(tmp_path):
    class _Dead:
        url = None

        def screenshot(self, **kw):
            raise RuntimeError("dead")

        def content(self):
            raise RuntimeError("dead")

    out = save_bundle(tmp_path, "x", page=_Dead(), extra={"a": object()})
    assert out.exists()


# ---------- engine ----------

def test_god_run_passthrough():
    calls = []

    def runner(cfg, headless, fn):
        calls.append(1)
        return fn("CTX")

    assert god_run(_cfg(), False, lambda ctx: ("ok", ctx), _runner=runner) == ("ok", "CTX")
    assert len(calls) == 1


def test_god_run_relaunches_on_browser_death():
    calls = []

    def runner(cfg, headless, fn):
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("Target closed: browser crashed")
        return "recovered"

    assert god_run(_cfg(level=4), False, lambda ctx: None, _runner=runner) == "recovered"
    assert len(calls) == 3


def test_god_run_gives_up_and_reraises_logic_errors():
    calls = []

    def runner(cfg, headless, fn):
        calls.append(1)
        raise ValueError("No trains found")

    try:
        god_run(_cfg(level=5), False, lambda ctx: None, _runner=runner)
        raise AssertionError("should have raised")
    except ValueError as exc:
        assert "No trains" in str(exc)
    assert len(calls) == 1  # logic errors don't burn relaunch rounds


def test_god_run_rotates_proxy_on_block():
    seen = []

    def runner(cfg, headless, fn):
        seen.append((cfg.browser.proxy or {}).get("server"))
        if (cfg.browser.proxy or {}).get("server") != "http://proxy-B:8080":
            raise BlockedError("access denied")
        return "unblocked"

    cfg = _cfg(level=4, proxies=[{"server": "http://proxy-A:8080"},
                                 {"server": "http://proxy-B:8080"}])
    assert god_run(cfg, False, lambda ctx: None, _runner=runner) == "unblocked"
    assert seen[0] is None and cfg.browser.proxy["server"] == "http://proxy-B:8080"
