"""Offline ETERNAL tests — journal, chaos drills, preflight, bodyguard."""

from datetime import timedelta
from pathlib import Path
from unittest import mock

from ticket_booker.god.chaos import DRILLS, ScriptedPage, run_drills
from ticket_booker.god.journal import Journal
from ticket_booker.god.preflight import preflight
from ticket_booker.irctc.payment import FAILURE_HINTS, is_failure_page

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.json"


def _cfg():
    from ticket_booker.config import load_config

    return load_config(EXAMPLE)


def _check(res, name):
    return next(c for c in res.checks if c["name"] == name)


# ---------- journal ----------

def test_journal_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    j = Journal()
    assert j.read() == []
    j.event("goto", "https://x.test", ok=True, ms=120)
    j.event("click", "Submit", ok=False)
    lines = j.read()
    assert [e["kind"] for e in lines] == ["goto", "click"]
    assert lines[0]["ms"] == 120 and lines[1]["ok"] is False


def test_journal_never_kills(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    j = Journal(base_dir=tmp_path / "j")
    j.event("x", "y")  # fine
    j._broken = True  # simulate dead disk
    j.event("x", "y")  # must not raise


# ---------- chaos ----------

def test_all_drills_pass(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    results = run_drills()
    assert len(results) == len(DRILLS) == 6
    for r in results:
        assert r.ok, f"{r.name}: {r.detail}"


def test_scripted_page_surface():
    p = ScriptedPage("hello")
    assert p.locator("body").inner_text() == "hello"
    assert p.locator("button").count() == 0
    assert p.locator("x").first.is_visible() is False
    p.goto("https://y.test")
    assert p.gotos == ["https://y.test"]


def test_perceptual_signature_never_crashes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from types import SimpleNamespace

    from ticket_booker.config import BruteCfg, CaptchaCfg
    from ticket_booker.tools.base import BruteContext

    cfg = SimpleNamespace(captcha=CaptchaCfg(), brute=BruteCfg(level=10))
    ctx = BruteContext(cfg, ScriptedPage("x"), False)
    sig = ctx._page_signature()  # screenshot raises -> pix "" (degraded, alive)
    assert sig[0] == "https://chaos.test/" and sig[2] == ""


# ---------- preflight ----------

def _dated(days_ahead):
    from ticket_booker.timing import now_ist

    cfg = _cfg()
    cfg.journey.date = (now_ist().date() + timedelta(days=days_ahead)).isoformat()
    return cfg


def test_preflight_happy_with_mocked_env():
    cfg = _dated(2)
    with mock.patch("camoufox.pkgman.installed_verstr", return_value="vTEST"):
        res = preflight(cfg)
    assert res.ok, [c for c in res.checks if not c["ok"]]
    assert _check(res, "arp.window")["ok"] is True


def test_preflight_past_and_arp():
    assert _check(preflight(_dated(-1)), "journey.date")["ok"] is False
    assert _check(preflight(_dated(61)), "arp.window")["ok"] is False
    assert _check(preflight(_dated(59)), "arp.window")["ok"] is True


def test_preflight_tatkal_past_open_warns_not_fails():
    cfg = _dated(0)  # journey today -> Tatkal opened yesterday
    assert cfg.journey.quota == "TQ"
    c = _check(preflight(cfg), "tatkal.window")
    assert c["ok"] is False and c["level"] == "warn"


def test_preflight_same_station_and_pax_limits():
    cfg = _dated(2)
    cfg.journey.to_station = cfg.journey.from_station
    assert _check(preflight(cfg), "stations")["ok"] is False
    cfg = _dated(2)
    cfg.passengers = [cfg.passengers[0].model_copy() for _ in range(5)]
    c = _check(preflight(cfg), "passengers.count")
    assert c["ok"] is False and "4/PNR" in c["msg"]


def test_preflight_warns_mobile_upi_solvers():
    cfg = _dated(2)
    cfg.preferences.mobile = ""
    cfg.irctc.mobile = ""
    cfg.payment.method = "upi"
    cfg.payment.upi_id = ""
    res = preflight(cfg)
    assert _check(res, "contact.mobile")["level"] == "warn"
    assert _check(res, "payment.upi")["level"] == "warn"
    solvers = _check(res, "captcha.solvers")
    assert set(solvers) == {"name", "ok", "msg", "level"}


def test_preflight_binaries_check_shape():
    res = preflight(_dated(2))
    b = _check(res, "browser.binaries")
    assert isinstance(b["ok"], bool) and b["msg"]


# ---------- bodyguard ----------

def test_failure_page_detector():
    assert is_failure_page("Payment Failed — try again") is True
    assert is_failure_page("TRANSACTION DECLINED by bank") is True
    assert is_failure_page("Booking Successful! PNR 1234567890") is False
    assert is_failure_page("") is False
    assert len(FAILURE_HINTS) >= 4
