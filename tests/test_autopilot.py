"""Offline tests for AUTOPILOT (hands-free booking), the live MONITOR and the
small popup window.

No browser: the booking stages are monkeypatched, the page is a fake that
returns JPEG bytes from ``screenshot()``, and Flask is driven with test_client.
"""

import io
import json
import threading
import time

import pytest

from ticket_booker.monitor import Monitor


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #

def jpeg(color="white", size=(40, 30)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


class FakePage:
    def __init__(self, body="", shots=True, url="https://www.irctc.co.in/nget/train-search"):
        self.body = body
        self.shots = shots
        self.url = url
        self.shot_calls = 0
        self.viewport = None
        self.js = []

    def screenshot(self, type="jpeg", quality=60, timeout=None):
        self.shot_calls += 1
        if not self.shots:
            raise RuntimeError("page is gone")
        return jpeg()

    def title(self):
        return "IRCTC"

    def set_viewport_size(self, size):
        self.viewport = size

    def evaluate(self, script, arg=None):
        self.js.append((script, arg))
        return [480, 860]

    def goto(self, url, wait_until=None):
        self.url = url


class FakeSession:
    def __init__(self, page):
        self.page = page

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def make_cfg(tmp_path, **pilot):
    """A valid AppConfig with a fake-ish profile dir and pilot overrides."""
    from ticket_booker.config import load_config

    data = {
        "irctc": {"username": "u", "password": "p", "mobile": "9999999999"},
        "journey": {"from_station": "NDLS", "to_station": "BCT", "date": "2030-01-01",
                    "class_code": "3A"},
        "passengers": [{"name": "Test User", "age": 30, "gender": "M", "berth": "LB"}],
        "browser": {"profile_dir": str(tmp_path / "profile")},
        "pilot": pilot or {},
    }
    cfg_file = tmp_path / "c.json"
    cfg_file.write_text(json.dumps(data), encoding="utf-8")
    return load_config(str(cfg_file))


# --------------------------------------------------------------------------- #
# MONITOR
# --------------------------------------------------------------------------- #

def test_monitor_records_steps():
    m = Monitor()
    m.begin("booking")
    m.step_now("login", "signing in")
    m.step_now("search", "train list")
    state = m.state()
    assert state["running"] is True
    assert state["step"] == "search"
    assert [e["step"] for e in state["events"]][-2:] == ["login", "search"]


def test_monitor_finish_sets_result():
    m = Monitor()
    m.begin("booking")
    m.finish(True, "BOOKED", pnr="1234567890")
    st = m.state()
    assert st["running"] is False and st["ok"] is True
    assert st["pnr"] == "1234567890"
    assert st["events"][-1]["level"] == "ok"


def test_monitor_event_ring_is_bounded():
    m = Monitor(max_events=5)
    m.begin("x")
    for i in range(20):
        m.step_now(f"s{i}")
    assert len(m.events(limit=100)) <= 6  # 5 ring + the begin() step


def test_monitor_snapshot_stores_frame():
    m = Monitor()
    m.begin("booking")
    page = FakePage()
    assert m.snapshot(page, "launched") is True
    data, seq = m.frame()
    assert data[:2] == b"\xff\xd8"  # JPEG magic
    assert seq == 1
    assert m.state()["frame_seq"] == 1


def test_monitor_snapshot_survives_dead_page():
    m = Monitor()
    m.begin("booking")
    assert m.snapshot(FakePage(shots=False)) is False
    assert m.frame() == (b"", 0)


def test_monitor_snapshot_without_page():
    m = Monitor()
    m.begin("booking")
    assert m.snapshot(None) is False


def test_monitor_frame_ring_is_bounded():
    m = Monitor(max_frames=3)
    m.begin("booking")
    for _ in range(10):
        m.snapshot(FakePage())
    assert m.state()["frame_count"] == 3


def test_monitor_is_thread_safe_for_pure_data():
    m = Monitor()
    m.begin("booking")

    def work(tag):
        for i in range(50):
            m.step_now(f"{tag}{i}")

    threads = [threading.Thread(target=work, args=(f"t{n}",)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    events = m.events(limit=1000)
    assert 0 < len(events) <= m.max_events
    assert m.state()["running"] is True


def test_monitor_reset_clears():
    m = Monitor()
    m.begin("x")
    m.snapshot(FakePage())
    m.reset()
    st = m.state()
    assert st["events"] == [] and st["frame_seq"] == 0 and st["running"] is False


# --------------------------------------------------------------------------- #
# small popup window
# --------------------------------------------------------------------------- #

def test_apply_small_window_resizes():
    from ticket_booker.browser import apply_small_window
    from ticket_booker.config import BrowserCfg

    cfg = BrowserCfg(small_window=True, window_width=420, window_height=800,
                     window_x=10, window_y=20)
    page = FakePage()
    assert apply_small_window(page, cfg) is True
    assert page.viewport == {"width": 420, "height": 800}
    assert page.js and page.js[0][1] == [420, 800, 10, 20]


def test_apply_small_window_off():
    from ticket_booker.browser import apply_small_window
    from ticket_booker.config import BrowserCfg

    page = FakePage()
    assert apply_small_window(page, BrowserCfg(small_window=False)) is False
    assert page.viewport is None


def test_apply_small_window_tolerates_failures():
    from ticket_booker.browser import apply_small_window
    from ticket_booker.config import BrowserCfg

    class Stubborn(FakePage):
        def set_viewport_size(self, size):
            raise RuntimeError("nope")

        def evaluate(self, script, arg=None):
            raise RuntimeError("nope")

    assert apply_small_window(Stubborn(), BrowserCfg(small_window=True)) is False


def test_parse_size():
    from ticket_booker.webui.launcher import parse_size

    assert parse_size("430x680") == (430, 680)
    assert parse_size("") == (430, 680)
    assert parse_size("garbage") == (430, 680)
    assert parse_size("100x100") == (240, 240)  # clamped to a usable minimum


# --------------------------------------------------------------------------- #
# AUTOPILOT — stage monkeypatching
# --------------------------------------------------------------------------- #

@pytest.fixture
def patched_stages(monkeypatch):
    """Replace every browser stage with a fast fake; returns a call recorder."""
    import ticket_booker.irctc.autopilot as ap

    calls = []

    def fake_launch(cfg, headless=None):
        page = FakePage()
        calls.append(("launch", page))
        return FakeSession(page)

    monkeypatch.setattr(ap, "launch_browser", fake_launch)
    monkeypatch.setattr(ap, "login", lambda page, auth, captcha, headless=False: calls.append(("login", None)) or True)
    monkeypatch.setattr(ap, "search_trains", lambda page, journey: calls.append(("search", None)))
    monkeypatch.setattr(ap, "select_train_and_class",
                        lambda page, journey, tatkal, clock: calls.append(("select", None)))
    monkeypatch.setattr(ap, "fill_passengers",
                        lambda page, pax, prefs: calls.append(("passengers", None)))
    monkeypatch.setattr(ap, "submit_and_continue", lambda page: calls.append(("submit", None)))
    monkeypatch.setattr(ap, "choose_upi", lambda page, upi: calls.append(("upi", None)))
    return calls


def test_autopilot_books_and_reports_pnr(tmp_path, patched_stages, monkeypatch):
    import ticket_booker.irctc.autopilot as ap

    cfg = make_cfg(tmp_path)
    pilot = ap.Autopilot(cfg, monitor=Monitor())
    monkeypatch.setattr(pilot, "_await_pnr", lambda page: "1234567890")

    report = pilot.run()

    assert report.ok is True
    assert report.pnr == "1234567890"
    assert report.cycles == 1
    assert "BOOKED" in report.message
    stages = [c[0] for c in patched_stages]
    # the documented chain: launch -> login -> search -> select -> pax -> submit -> pay
    assert stages[:7] == ["launch", "login", "search", "select",
                          "passengers", "submit", "upi"]


def test_autopilot_records_steps_on_monitor(tmp_path, patched_stages, monkeypatch):
    import ticket_booker.irctc.autopilot as ap

    m = Monitor()
    cfg = make_cfg(tmp_path)
    pilot = ap.Autopilot(cfg, monitor=m)
    monkeypatch.setattr(pilot, "_await_pnr", lambda page: "9999999999")

    pilot.run()

    steps = [e["step"] for e in m.state()["events"]]
    assert "login" in steps and "search" in steps and "payment" in steps
    assert "booked" in steps
    assert m.state()["pnr"] == "9999999999"
    assert m.state()["running"] is False


def test_autopilot_streams_frames(tmp_path, patched_stages, monkeypatch):
    import ticket_booker.irctc.autopilot as ap

    m = Monitor()
    pilot = ap.Autopilot(make_cfg(tmp_path), monitor=m)
    monkeypatch.setattr(pilot, "_await_pnr", lambda page: "1111111111")

    pilot.run()

    data, seq = m.frame()
    assert seq > 0 and data[:2] == b"\xff\xd8"
    assert m.state()["frame_count"] > 0


def test_autopilot_retries_then_succeeds(tmp_path, patched_stages, monkeypatch):
    import ticket_booker.irctc.autopilot as ap

    cfg = make_cfg(tmp_path, retry_delay_seconds=0, auto_submit=False)
    pilot = ap.Autopilot(cfg, monitor=Monitor())
    attempts = {"n": 0}

    def pnr(page):
        attempts["n"] += 1
        return "1234567890" if attempts["n"] >= 2 else None

    monkeypatch.setattr(pilot, "_await_pnr", pnr)

    report = pilot.run()

    assert report.ok is True
    assert report.cycles == 2
    steps = [e["step"] for e in pilot.monitor.state()["events"]]
    assert "retrying" in steps


def test_autopilot_gives_up_after_max_cycles(tmp_path, patched_stages, monkeypatch):
    import ticket_booker.irctc.autopilot as ap

    cfg = make_cfg(tmp_path, max_cycles=2, retry_delay_seconds=0, auto_submit=False)
    pilot = ap.Autopilot(cfg, monitor=Monitor())
    monkeypatch.setattr(pilot, "_await_pnr", lambda page: None)

    report = pilot.run()

    assert report.ok is False
    assert report.cycles == 2
    assert "Gave up" in report.message


def test_autopilot_never_rebooks_after_submitting_payment(tmp_path, patched_stages, monkeypatch):
    """The money guard: a submitted payment must never trigger another cycle."""
    import ticket_booker.irctc.autopilot as ap

    cfg = make_cfg(tmp_path, max_cycles=5, retry_delay_seconds=0)
    pilot = ap.Autopilot(cfg, monitor=Monitor())
    monkeypatch.setattr(pilot, "_await_pnr", lambda page: None)

    report = pilot.run()

    assert report.ok is False
    assert report.cycles == 1  # stopped immediately, no second cycle
    assert "not booked twice" in report.message
    launches = [c for c in patched_stages if c[0] == "launch"]
    assert len(launches) == 1


def test_autopilot_survives_stage_crash(tmp_path, patched_stages, monkeypatch):
    import ticket_booker.irctc.autopilot as ap

    cfg = make_cfg(tmp_path, max_cycles=2, retry_delay_seconds=0, auto_submit=False)

    def boom(page, auth, captcha, headless=False):
        raise RuntimeError("IRCTC down")

    monkeypatch.setattr(ap, "login", boom)
    pilot = ap.Autopilot(cfg, monitor=Monitor())

    report = pilot.run()  # must not raise

    assert report.ok is False
    assert report.cycles == 2


def test_autopilot_forces_non_blocking_captcha(tmp_path):
    import ticket_booker.irctc.autopilot as ap

    cfg = make_cfg(tmp_path)
    cfg.captcha.mode = "manual"
    cfg.captcha.on_failure = "manual"
    ap.Autopilot(cfg, monitor=Monitor()).prepare()
    assert cfg.captcha.mode == "auto"
    assert cfg.captcha.on_failure == "error"


def test_autopilot_switches_manual_payment_to_upi(tmp_path):
    import ticket_booker.irctc.autopilot as ap

    cfg = make_cfg(tmp_path)
    cfg.payment.method = "manual"
    ap.Autopilot(cfg, monitor=Monitor()).prepare()
    assert cfg.payment.method == "upi"
    assert cfg.payment.auto_submit is True


def test_autopilot_respects_auto_submit_off(tmp_path):
    import ticket_booker.irctc.autopilot as ap

    cfg = make_cfg(tmp_path, auto_submit=False)
    ap.Autopilot(cfg, monitor=Monitor()).prepare()
    assert cfg.payment.auto_submit is False


def test_autopilot_pilot_disabled_keeps_manual_entry(tmp_path):
    import ticket_booker.irctc.autopilot as ap

    cfg = make_cfg(tmp_path, force_auto_captcha=False)
    cfg.captcha.mode = "manual"
    ap.Autopilot(cfg, monitor=Monitor()).prepare()
    assert cfg.captcha.mode == "manual"


def test_pilot_report_serialises():
    from ticket_booker.irctc.autopilot import PilotReport

    d = PilotReport(True, "1234567890", 2, "ok", ["a"], 12.345).as_dict()
    assert d["ok"] is True and d["pnr"] == "1234567890"
    assert d["seconds"] == 12.3 and d["steps"] == ["a"]


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #

def test_pilot_config_defaults(tmp_path):
    cfg = make_cfg(tmp_path)
    assert cfg.pilot.enabled is True
    assert cfg.pilot.max_cycles == 4
    assert cfg.pilot.auto_submit is True
    assert cfg.pilot.monitor_size == "430x680"


def test_browser_small_window_defaults(tmp_path):
    cfg = make_cfg(tmp_path)
    assert cfg.browser.small_window is False  # opt-in for normal runs
    assert cfg.browser.window_width == 480


def test_payment_auto_submit_defaults_off(tmp_path):
    cfg = make_cfg(tmp_path)
    assert cfg.payment.auto_submit is False


# --------------------------------------------------------------------------- #
# WebUI
# --------------------------------------------------------------------------- #

@pytest.fixture
def client(tmp_path):
    pytest.importorskip("flask")
    from ticket_booker.config import load_config  # noqa: F401
    from ticket_booker.webui.server import create_app

    data = {
        "irctc": {"username": "u", "password": "p", "mobile": "9999999999"},
        "journey": {"from_station": "NDLS", "to_station": "BCT", "date": "2030-01-01"},
        "passengers": [{"name": "Test User", "age": 30, "gender": "M", "berth": "LB"}],
        "browser": {"profile_dir": str(tmp_path / "p")},
    }
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps(data), encoding="utf-8")
    app = create_app(str(cfg))
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_monitor_page_served(client):
    html = client.get("/monitor").get_data(as_text=True)
    assert "LIVE" in html
    assert "/api/monitor/state" in html
    assert "/api/monitor/frame.jpg" in html


def test_monitor_state_endpoint(client):
    from ticket_booker.monitor import get_monitor

    m = get_monitor()
    m.reset()
    m.begin("booking")
    m.step_now("login", "signing in")
    payload = client.get("/api/monitor/state").get_json()
    assert payload["running"] is True
    assert payload["step"] == "login"
    m.reset()


def test_monitor_frame_endpoint_returns_jpeg(client):
    from ticket_booker.monitor import get_monitor

    m = get_monitor()
    m.reset()
    m.begin("booking")
    m.snapshot(FakePage())
    resp = client.get("/api/monitor/frame.jpg")
    assert resp.status_code == 200
    assert resp.mimetype == "image/jpeg"
    assert resp.data[:2] == b"\xff\xd8"
    assert resp.headers["X-Frame-Seq"] == "1"
    m.reset()


def test_monitor_frame_endpoint_204_when_empty(client):
    from ticket_booker.monitor import get_monitor

    get_monitor().reset()
    assert client.get("/api/monitor/frame.jpg").status_code == 204


def test_autopilot_endpoint_starts_job(client, monkeypatch):
    import ticket_booker.irctc.autopilot as ap
    from ticket_booker.irctc.autopilot import PilotReport

    called = {}

    def fake_run(cfg, headless=None):
        called["yes"] = True
        return PilotReport(True, "1234567890", 1, "BOOKED", [], 1.0)

    monkeypatch.setattr(ap, "run_autopilot", fake_run)

    resp = client.post("/api/autopilot", json={"brutality": "void", "small_window": True})
    assert resp.status_code == 200
    job = resp.get_json()["job"]
    assert job["kind"] == "auto"

    for _ in range(60):
        if called.get("yes"):
            break
        time.sleep(0.05)
    assert called.get("yes") is True


def test_dashboard_has_autopilot_button(client):
    html = client.get("/").get_data(as_text=True)
    assert "AUTOPILOT" in html
    assert "/api/autopilot" in html
    assert "tb-monitor" in html  # the small popup window name


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def test_cli_auto_parses_flags():
    from ticket_booker.cli import build_parser

    a = build_parser().parse_args(["auto"])
    assert a.command == "auto"
    assert a.small_window is None      # default -> autopilot turns it on
    assert a.popup is False
    assert a.cycles == 0

    b = build_parser().parse_args(
        ["auto", "--cycles", "3", "--no-small-window", "--popup", "--monitor-size", "500x700"])
    assert b.cycles == 3 and b.small_window is False
    assert b.popup is True and b.monitor_size == "500x700"


def test_cli_auto_runs_hands_free(tmp_path, monkeypatch, capsys):
    import ticket_booker.irctc.autopilot as ap
    from ticket_booker.cli import build_parser, cmd_auto
    from ticket_booker.irctc.autopilot import PilotReport

    data = {
        "irctc": {"username": "u", "password": "p", "mobile": "9999999999"},
        "journey": {"from_station": "NDLS", "to_station": "BCT", "date": "2030-01-01"},
        "passengers": [{"name": "Test User", "age": 30, "gender": "M", "berth": "LB"}],
        "browser": {"profile_dir": str(tmp_path / "p")},
    }
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps(data), encoding="utf-8")

    seen = {}

    def fake_run(self):
        seen["small"] = self.cfg.browser.small_window
        return PilotReport(True, "1234567890", 1, "BOOKED", [], 2.0)

    monkeypatch.setattr(ap.Autopilot, "run", fake_run)

    args = build_parser().parse_args(["auto", "-c", str(cfg)])
    assert cmd_auto(args) == 0
    out = capsys.readouterr().out
    assert "AUTOPILOT" in out
    assert "1234567890" in out
    assert seen["small"] is True  # watchable by default


def test_cli_auto_exit_code_on_failure(tmp_path, monkeypatch):
    import ticket_booker.irctc.autopilot as ap
    from ticket_booker.cli import build_parser, cmd_auto
    from ticket_booker.irctc.autopilot import PilotReport

    data = {
        "irctc": {"username": "u", "password": "p", "mobile": "9999999999"},
        "journey": {"from_station": "NDLS", "to_station": "BCT", "date": "2030-01-01"},
        "passengers": [{"name": "Test User", "age": 30, "gender": "M", "berth": "LB"}],
        "browser": {"profile_dir": str(tmp_path / "p")},
    }
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(ap.Autopilot, "run",
                        lambda self: PilotReport(False, None, 4, "sold out", [], 1.0))
    assert cmd_auto(build_parser().parse_args(["auto", "-c", str(cfg)])) == 1


# --------------------------------------------------------------------------- #
# DEMO reel (popup preview without a browser)
# --------------------------------------------------------------------------- #

def test_demo_draws_a_jpeg_frame():
    from ticket_booker.demo import _draw

    blob = _draw("IRCTC - LOGIN", "username •••   captcha [OK]")
    assert blob[:2] == b"\xff\xd8"  # JPEG


def test_demo_reel_fills_the_monitor(monkeypatch):
    from ticket_booker import demo

    monkeypatch.setattr(demo, "SCRIPT", [
        (0.0, "login", "signed in", "ok"),
        (0.0, "booked", "PNR 0000000000 (demo)", "ok"),
    ])
    m = Monitor()
    assert demo.start_demo(m, speed=50) is True
    for _ in range(100):
        if not m.state()["running"] and m.state()["ok"] is not None:
            break
        time.sleep(0.05)
    st = m.state()
    assert st["ok"] is True
    assert st["pnr"] == demo.DEMO_PNR
    assert st["frame_seq"] >= 1
    assert any("demo" in e["detail"] for e in st["events"])


def test_demo_is_single_flight(monkeypatch):
    from ticket_booker import demo

    monkeypatch.setattr(demo, "SCRIPT", [(0.4, "login", "slow", "info")] * 3)
    m = Monitor()
    assert demo.start_demo(m, speed=2) is True
    assert demo.start_demo(m, speed=2) is False  # already playing
    for _ in range(100):
        if not demo.demo_running():
            break
        time.sleep(0.05)


def test_demo_endpoint(client):
    resp = client.post("/api/monitor/demo")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
