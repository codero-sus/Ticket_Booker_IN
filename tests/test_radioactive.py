"""Offline RADIOACTIVE tests — tiers, pacer, vault, hydra, ensemble, doomsday."""

import time
from pathlib import Path

from ticket_booker.god.hydra import heads_for, hydra_race
from ticket_booker.god.pacer import Pacer
from ticket_booker.god.session_vault import load_vault, save_vault, vault_status
from ticket_booker.god.signals import tier_of, title_for_level
from ticket_booker.tools.base import ToolResult

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.json"


def _cfg(level=4, heads=0):
    from ticket_booker.config import load_config

    cfg = load_config(EXAMPLE)
    cfg.brute.level = level
    cfg.brute.hydra_heads = heads
    return cfg


# ---------- tiers & titles ----------

def test_tier_mapping():
    assert [tier_of(n) for n in (1, 2, 3, 4, 5)] == [1, 2, 3, 4, 5]
    assert tier_of(6) == tier_of(9) == 6
    assert tier_of(10) == tier_of(999999) == 7
    assert tier_of(9223372036854775807) == 7
    assert tier_of("junk") == 3


def test_titles():
    assert title_for_level(1) == "CALM"
    assert title_for_level(5) == "ULTIMATE GOD"
    assert "OMEGA" in title_for_level(7)
    assert "RADIOACTIVE" in title_for_level(42)
    assert "9223372036854775807" in title_for_level(9223372036854775807)


def test_int64max_level_validates():
    from ticket_booker.config import BruteCfg

    assert BruteCfg(level=9223372036854775807).level == 9223372036854775807


# ---------- pacer ----------

def test_pacer_slows_on_slow_site():
    p = Pacer()
    base = p.hi
    for _ in range(25):
        p.record(3.0)
    assert p.hi > base
    lo, hi = p.delay()
    assert 0 < lo < hi <= p.max_hi


def test_pacer_speeds_on_fast_site():
    p = Pacer(hi=5.0)
    for _ in range(25):
        p.record(0.05)
    assert p.hi < 5.0
    p2 = Pacer()
    p2.sleep()  # must not crash; quick on defaults


def test_pacer_ignores_garbage():
    p = Pacer()
    p.record("junk")
    p.record(-5)
    assert p.delay()[1] > 0


# ---------- vault ----------

class _FakeContext:
    def __init__(self):
        self._cookies = []

    def cookies(self):
        return list(self._cookies)

    def add_cookies(self, cs):
        self._cookies.extend(cs)


def _cookie(name="sid", value="s3cret"):
    return {"name": name, "value": value, "url": "https://www.irctc.co.in",
            "path": "/", "expires": time.time() + 3600}


def test_vault_roundtrip(tmp_path):
    vault = tmp_path / "vault.json"
    src = _FakeContext()
    src.add_cookies([_cookie(), _cookie("a", "b")])
    assert save_vault(src, vault) == 2
    raw = vault.read_text(encoding="utf-8")
    assert "s3cret" not in raw  # obfuscated, not plaintext
    dst = _FakeContext()
    assert load_vault(dst, vault) == 2
    assert dst.cookies()[0]["value"] == "s3cret"
    st = vault_status(vault)
    assert st["exists"] and st["count"] == 2 and st["saved_on"]


def test_vault_skips_expired_and_garbage(tmp_path):
    vault = tmp_path / "v.json"
    src = _FakeContext()
    stale = _cookie("old", "x")
    stale["expires"] = time.time() - 10
    src.add_cookies([stale, _cookie("fresh", "y")])
    assert save_vault(src, vault) == 2
    dst = _FakeContext()
    assert load_vault(dst, vault) == 1
    assert dst.cookies()[0]["name"] == "fresh"
    assert load_vault(dst, tmp_path / "missing.json") == 0
    (tmp_path / "bad.json").write_text("garbage!!", encoding="utf-8")
    assert load_vault(dst, tmp_path / "bad.json") == 0


# ---------- hydra ----------

def test_heads_for():
    assert heads_for(_cfg(4, 0)) == 1
    assert heads_for(_cfg(4, 3)) == 1  # below OMEGA: single head, always
    assert heads_for(_cfg(7, 0)) == 2
    assert heads_for(_cfg(10, 0)) == 3
    assert heads_for(_cfg(10, 1)) == 1
    assert heads_for(_cfg(10, 99)) == 3  # hard cap


def test_hydra_first_wins():
    def runner(cfg, headless, fn):
        tag = str(cfg.browser.profile_dir)
        if ".hydra1" in tag:
            time.sleep(0.3)
            return ToolResult(True, {"head": 1}, "slow win")
        time.sleep(0.02)
        return ToolResult(True, {"head": 0}, "fast win")

    res = hydra_race(_cfg(10, 2), False, lambda ctx: None, _runner=runner)
    assert res.ok and res.data["head"] == 0


def test_hydra_all_fail_returns_report():
    def runner(cfg, headless, fn):
        return ToolResult(False, {"why": "nope"}, "failed")

    res = hydra_race(_cfg(7, 2), False, lambda ctx: None, _runner=runner)
    assert res.ok is False and res.data["why"] == "nope"


def test_hydra_dying_head_cannot_kill_race():
    def runner(cfg, headless, fn):
        if ".hydra0" in str(cfg.browser.profile_dir):
            raise RuntimeError("Target closed: boom")
        return ToolResult(True, {"head": 1}, "survivor")

    res = hydra_race(_cfg(7, 2), False, lambda ctx: None, _runner=runner)
    assert res.ok and res.data["head"] == 1


def test_hydra_single_head_passthrough():
    calls = []

    def runner(cfg, headless, fn):
        calls.append(1)
        return "direct"

    assert hydra_race(_cfg(4, 0), False, lambda ctx: None, _runner=runner) == "direct"
    assert len(calls) == 1


# ---------- ensemble vote ----------

def test_vote_texts():
    from ticket_booker.captcha.ocr_solver import vote_texts

    assert vote_texts([]) is None
    # close race -> frequency wins over lone slightly-higher confidence
    out = vote_texts([("AB12", 80.0), ("AB12", 79.0), ("XY99", 82.0)])
    assert out[0] == "AB12"
    # runaway confidence still wins
    out = vote_texts([("AB12", 40.0), ("XY99", 95.0)])
    assert out[0] == "XY99"


# ---------- doomsday ----------

def test_doomsday_budget(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from types import SimpleNamespace

    from ticket_booker.config import BruteCfg, CaptchaCfg
    from ticket_booker.tools.base import BruteContext

    class _DeadPage:
        url = "https://x.test"

        def screenshot(self, **kw):
            raise RuntimeError("dead")

        def content(self):
            raise RuntimeError("dead")

    cfg = SimpleNamespace(captcha=CaptchaCfg(), brute=BruteCfg(level=1, max_tool_minutes=25))
    ctx = BruteContext(cfg, _DeadPage(), False)
    assert ctx._deadline is not None
    ctx._deadline = time.time() - 1  # budget blown
    try:
        ctx.brute(lambda: "never", "doom", retries=3, reload_between=False)
        raise AssertionError("doomsday should have fired")
    except TimeoutError as exc:
        assert "DOOMSDAY" in str(exc)


def test_no_doomsday_when_immortal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from types import SimpleNamespace

    from ticket_booker.config import BruteCfg, CaptchaCfg
    from ticket_booker.tools.base import BruteContext

    cfg = SimpleNamespace(captcha=CaptchaCfg(),
                          brute=BruteCfg(level=1, max_tool_minutes=0))
    ctx = BruteContext(cfg, object(), False)
    assert ctx._deadline is None
    assert ctx.brute(lambda: "fine", "x", retries=1, reload_between=False) == "fine"
