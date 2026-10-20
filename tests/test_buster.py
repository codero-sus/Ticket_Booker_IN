"""Offline tests for the Buster bridge: click the icon, then PLAY.

The fake page below mirrors the real reCAPTCHA iframe layout that Buster's
content script targets (bframe = challenge frame, anchor = checkbox frame).
It also emulates the extension: when `with_extension=True`, a
`#solver-button` exists and clicking it "solves" the challenge, exactly like
the real Buster code path.
"""

import pytest

from ticket_booker.captcha.buster import (
    ANSWER_INPUT,
    AUDIO_SRC,
    ICON_SELECTOR,
    PLAY_SELECTOR,
    VERIFY_BUTTON,
    BusterResult,
    BusterSolver,
    anchor_checked,
    buster_xpi_path,
    download_extension,
    extension_installed,
)


# --------------------------------------------------------------------------- #
# fake DOM
# --------------------------------------------------------------------------- #

class FakeLocator:
    def __init__(self, frame, selector):
        self.frame = frame
        self.selector = selector
        self.first = self

    def count(self):
        return 1 if self.selector in self.frame.nodes else 0

    def click(self, timeout=None):
        if self.selector not in self.frame.nodes:
            raise RuntimeError(f"no {self.selector}")
        self.frame.clicks.append(self.selector)
        self.frame.on_click(self.selector)

    def get_attribute(self, name, timeout=None):
        node = self.frame.nodes.get(self.selector)
        if node is None:
            raise RuntimeError(f"no {self.selector}")
        return node.get(name)

    def fill(self, value, timeout=None):
        self.frame.nodes[self.selector]["value"] = value

    def press_sequentially(self, value, delay=None):
        self.frame.nodes[self.selector]["value"] = value


class FakeFrame:
    def __init__(self, url, nodes=None):
        self.url = url
        self.nodes = dict(nodes or {})
        self.clicks = []

    def locator(self, selector):
        return FakeLocator(self, selector)

    def wait_for_selector(self, selector, timeout=None, state=None):
        if selector not in self.nodes:
            raise TimeoutError(selector)
        return FakeLocator(self, selector)

    def evaluate(self, script, arg=None):
        return True

    def on_click(self, selector):
        pass


class FakeAnchor(FakeFrame):
    """Clicking the checkbox only *opens* the challenge (like the real widget)."""

    solves_on_checkbox = False

    def on_click(self, selector):
        if selector == "#recaptcha-anchor" and self.solves_on_checkbox:
            self.nodes["#recaptcha-anchor"]["aria-checked"] = "true"


class FakeChallenge(FakeFrame):
    """Emulates Buster's own behaviour when its icon is clicked."""

    def __init__(self, url, anchor, nodes=None, solve_on_icon=True):
        super().__init__(url, nodes)
        self.anchor = anchor
        self.solve_on_icon = solve_on_icon

    def on_click(self, selector):
        if selector == ICON_SELECTOR and self.solve_on_icon:
            self.anchor.nodes["#recaptcha-anchor"]["aria-checked"] = "true"
        if selector == VERIFY_BUTTON:
            answer = self.nodes.get(ANSWER_INPUT, {}).get("value", "")
            if answer == "goodanswer":
                self.anchor.nodes["#recaptcha-anchor"]["aria-checked"] = "true"


class FakePage:
    def __init__(self, frames):
        self.frames = frames

    def wait_for_timeout(self, ms):
        pass


def build_page(with_extension=False, with_challenge=True):
    anchor_nodes = {"#recaptcha-anchor": {"aria-checked": "false"}}
    anchor = FakeAnchor("https://www.google.com/recaptcha/api2/anchor?k=x", anchor_nodes)
    frames = [anchor]
    challenge = None
    if with_challenge:
        nodes = {"#recaptcha-audio-button": {}, ANSWER_INPUT: {"value": ""},
                 VERIFY_BUTTON: {}, "#recaptcha-reload-button": {}}
        if with_extension:
            nodes[ICON_SELECTOR] = {"data-tooltip": "Solve with Buster"}
        challenge = FakeChallenge(
            "https://www.google.com/recaptcha/api2/bframe?k=x", anchor, nodes)
        frames.append(challenge)
    return FakePage(frames), anchor, challenge


# --------------------------------------------------------------------------- #
# selectors are the real Buster ones
# --------------------------------------------------------------------------- #

def test_selectors_match_buster_source():
    assert ICON_SELECTOR == "#solver-button"
    assert PLAY_SELECTOR == ".rc-audiochallenge-play-button > button"
    assert AUDIO_SRC == "audio#audio-source"
    assert ANSWER_INPUT == "#audio-response"
    assert VERIFY_BUTTON == "#recaptcha-verify-button"


# --------------------------------------------------------------------------- #
# capability detection
# --------------------------------------------------------------------------- #

def test_icon_present_when_extension_loaded():
    page, _, _ = build_page(with_extension=True)
    assert BusterSolver(page=page).icon_present(page) is True


def test_icon_absent_without_extension():
    page, _, _ = build_page(with_extension=False)
    assert BusterSolver(page=page).icon_present(page) is False


def test_status_shape():
    page, _, _ = build_page(with_extension=True)
    st = BusterSolver(page=page).status(page)
    assert st["extension_detected"] is True
    assert st["icon_selector"] == "#solver-button"
    assert st["play_selector"] == PLAY_SELECTOR


def test_available_requires_page():
    assert BusterSolver().available() is False
    page, _, _ = build_page()
    assert BusterSolver(page=page).available() is True


# --------------------------------------------------------------------------- #
# the requested gesture: icon then PLAY
# --------------------------------------------------------------------------- #

def test_click_icon_hits_solver_button():
    page, _, challenge = build_page(with_extension=True)
    solver = BusterSolver(page=page)
    assert solver.click_icon(page) is True
    assert ICON_SELECTOR in challenge.clicks


def test_click_icon_without_extension_returns_false():
    page, _, challenge = build_page(with_extension=False)
    assert BusterSolver(page=page).click_icon(page) is False
    assert challenge.clicks == []


def test_click_play_hits_play_button():
    page, _, challenge = build_page()
    challenge.nodes[PLAY_SELECTOR] = {}
    solver = BusterSolver(page=page)
    assert solver.click_play(page) is True
    assert PLAY_SELECTOR in challenge.clicks


def test_click_play_falls_back_to_aria_label():
    page, _, challenge = build_page()
    challenge.nodes["button[aria-label='Play']"] = {}
    assert BusterSolver(page=page).click_play(page) is True


def test_click_play_absent():
    page, _, _ = build_page()
    assert BusterSolver(page=page).click_play(page) is False


# --------------------------------------------------------------------------- #
# full solve — extension path
# --------------------------------------------------------------------------- #

def test_solve_via_extension_icon():
    page, anchor, challenge = build_page(with_extension=True)
    res = BusterSolver(page=page, mode="auto", timeout=0.3).solve(page)
    assert res.solved is True
    assert res.method == "extension"
    assert ICON_SELECTOR in challenge.clicks          # the icon was clicked
    assert anchor_checked(anchor) is True


def test_solve_extension_mode_forced():
    page, _, challenge = build_page(with_extension=True)
    res = BusterSolver(page=page, mode="extension", timeout=0.3).solve(page)
    assert res.solved and res.method == "extension"
    assert ICON_SELECTOR in challenge.clicks


def test_extension_mode_without_extension_fails_cleanly():
    page, _, _ = build_page(with_extension=False)
    res = BusterSolver(page=page, mode="extension", timeout=0.3).solve(page)
    assert res.solved is False


def test_solve_no_recaptcha_is_success():
    page = FakePage([])
    res = BusterSolver(page=page, timeout=0.3).solve(page)
    assert res.solved is True and res.message == "no reCAPTCHA on page"


def test_solve_already_solved_short_circuits():
    page, anchor, challenge = build_page(with_extension=True)
    anchor.nodes["#recaptcha-anchor"]["aria-checked"] = "true"
    res = BusterSolver(page=page, timeout=0.3).solve(page)
    assert res.solved is True and res.message == "already solved"
    assert challenge.clicks == []


def test_checkbox_alone_passes():
    page, anchor, _ = build_page(with_challenge=False)
    anchor.solves_on_checkbox = True
    res = BusterSolver(page=page, timeout=0.3).solve(page)
    assert res.solved is True
    assert res.method == "checkbox"
    assert anchor.nodes["#recaptcha-anchor"]["aria-checked"] == "true"


def test_solve_without_page_returns_result():
    res = BusterSolver().solve()
    assert res.solved is False
    assert "no page" in res.message


# --------------------------------------------------------------------------- #
# native path (no extension): audio -> PLAY -> transcribe -> submit
# --------------------------------------------------------------------------- #

def test_native_clicks_play_and_submits(monkeypatch):
    page, anchor, challenge = build_page(with_extension=False)
    challenge.nodes[AUDIO_SRC] = {"src": "https://example/audio.mp3"}
    challenge.nodes[PLAY_SELECTOR] = {}

    solver = BusterSolver(page=page, mode="native", timeout=0.3)

    monkeypatch.setattr(solver, "_transcribe", lambda url: "goodanswer")

    res = solver.solve(page)

    assert res.solved is True and res.method == "native"
    assert PLAY_SELECTOR in challenge.clicks          # PLAY was pressed
    assert VERIFY_BUTTON in challenge.clicks          # answer submitted
    assert challenge.nodes[ANSWER_INPUT]["value"] == "goodanswer"


def test_native_switches_to_audio_tab(monkeypatch):
    page, anchor, challenge = build_page(with_extension=False)
    challenge.nodes[PLAY_SELECTOR] = {}

    def on_click(selector):
        if selector == "#recaptcha-audio-button":
            challenge.nodes[AUDIO_SRC] = {"src": "https://example/audio.mp3"}
        FakeChallenge.on_click(challenge, selector)

    challenge.on_click = on_click
    solver = BusterSolver(page=page, mode="native", timeout=0.3)
    monkeypatch.setattr(solver, "_transcribe", lambda url: "goodanswer")

    res = solver.solve(page)
    assert res.solved is True
    assert "#recaptcha-audio-button" in challenge.clicks


def test_native_wrong_answer_retries(monkeypatch):
    page, anchor, challenge = build_page(with_extension=False)
    challenge.nodes[AUDIO_SRC] = {"src": "https://example/audio.mp3"}
    challenge.nodes[PLAY_SELECTOR] = {}

    solver = BusterSolver(page=page, mode="native", max_attempts=2, timeout=0.3)
    monkeypatch.setattr(solver, "_transcribe", lambda url: "wronganswer")

    res = solver.solve(page)
    assert res.solved is False
    assert res.attempts == 2


def test_auto_falls_back_to_native(monkeypatch):
    page, anchor, challenge = build_page(with_extension=False)
    challenge.nodes[AUDIO_SRC] = {"src": "https://example/audio.mp3"}
    challenge.nodes[PLAY_SELECTOR] = {}

    solver = BusterSolver(page=page, mode="auto", timeout=0.3)
    monkeypatch.setattr(solver, "_transcribe", lambda url: "goodanswer")
    res = solver.solve(page)
    assert res.solved is True and res.method == "native"


def test_auto_prefers_extension_when_present(monkeypatch):
    page, anchor, challenge = build_page(with_extension=True)
    solver = BusterSolver(page=page, mode="auto", timeout=0.3)
    called = {"native": False}

    def boom(url):
        called["native"] = True
        return ""

    monkeypatch.setattr(solver, "_transcribe", boom)
    res = solver.solve(page)
    assert res.method == "extension"
    assert called["native"] is False


def test_transcribe_failure_is_not_fatal():
    page, anchor, challenge = build_page(with_extension=False)
    challenge.nodes[AUDIO_SRC] = {"src": "https://example/audio.mp3"}

    solver = BusterSolver(page=page, mode="native", max_attempts=1, timeout=0.3)

    def raise_exc(url):
        raise RuntimeError("no ffmpeg")

    solver._transcribe = raise_exc
    res = solver.solve(page)
    assert res.solved is False  # clean failure, no exception escapes


# --------------------------------------------------------------------------- #
# extension install helpers
# --------------------------------------------------------------------------- #

def test_xpi_path_from_config():
    from ticket_booker.config import BusterCfg

    cfg = BusterCfg(extension_path="/tmp/x/buster.xpi")
    assert str(buster_xpi_path(cfg)) == "/tmp/x/buster.xpi"


def test_extension_installed_false_by_default(tmp_path):
    from ticket_booker.config import BusterCfg

    cfg = BusterCfg(extension_path=str(tmp_path / "nope.xpi"))
    assert extension_installed(cfg) is False


def test_extension_installed_true(tmp_path):
    from ticket_booker.config import BusterCfg

    xpi = tmp_path / "buster.xpi"
    xpi.write_bytes(b"PK\x03\x04fake")
    assert extension_installed(BusterCfg(extension_path=str(xpi))) is True


def test_download_extension_validates_zip(monkeypatch, tmp_path):
    import ticket_booker.captcha.buster as bmod

    class Resp:
        content = b"PK\x03\x04signed-xpi"

        def raise_for_status(self):
            pass

    monkeypatch.setattr("requests.get", lambda *a, **k: Resp())
    out = download_extension(tmp_path / "sub" / "buster.xpi")
    assert out.exists() and out.read_bytes().startswith(b"PK")


def test_download_extension_rejects_non_xpi(monkeypatch, tmp_path):
    class Resp:
        content = b"<html>maintenance</html>"

        def raise_for_status(self):
            pass

    monkeypatch.setattr("requests.get", lambda *a, **k: Resp())
    with pytest.raises(RuntimeError):
        download_extension(tmp_path / "buster.xpi")


# --------------------------------------------------------------------------- #
# manager + config wiring
# --------------------------------------------------------------------------- #

def test_manager_builds_buster_solver():
    from ticket_booker.captcha.manager import AutoCaptcha
    from ticket_booker.config import CaptchaCfg

    ac = AutoCaptcha(CaptchaCfg())
    assert ac.buster is not None
    assert ac.buster.mode == "auto"
    assert ac.buster_status()["enabled"] is True


def test_manager_buster_disabled():
    from ticket_booker.captcha.manager import AutoCaptcha
    from ticket_booker.config import CaptchaCfg

    cfg = CaptchaCfg()
    cfg.buster.enabled = False
    ac = AutoCaptcha(cfg)
    assert ac.buster is None
    assert ac.buster_status() == {"enabled": False}


def test_manager_attach_page_hands_page_to_buster():
    from ticket_booker.captcha.manager import AutoCaptcha
    from ticket_booker.config import CaptchaCfg

    cfg = CaptchaCfg()
    cfg.buster.timeout = 0.3
    ac = AutoCaptcha(cfg)
    page, _, _ = build_page(with_extension=True)
    ac.attach_page(page)
    assert ac.buster.page is page


def test_manager_solve_recaptcha_uses_buster():
    from ticket_booker.captcha.manager import AutoCaptcha
    from ticket_booker.config import CaptchaCfg

    cfg = CaptchaCfg()
    cfg.buster.timeout = 0.3
    ac = AutoCaptcha(cfg)
    page, anchor, challenge = build_page(with_extension=True)
    ac.attach_page(page)
    res = ac.solve_recaptcha()
    assert res.solved is True and res.method == "extension"
    assert ICON_SELECTOR in challenge.clicks


def test_manager_solve_recaptcha_without_page():
    from ticket_booker.captcha.manager import AutoCaptcha
    from ticket_booker.config import CaptchaCfg

    res = AutoCaptcha(CaptchaCfg()).solve_recaptcha()
    assert res.solved is False


def test_config_autoloads_extension_when_present(tmp_path):
    import json

    from ticket_booker.config import load_config

    xpi = tmp_path / "buster.xpi"
    xpi.write_bytes(b"PK\x03\x04")
    cfg_file = tmp_path / "c.json"
    cfg_file.write_text(json.dumps({
        "irctc": {"username": "u", "password": "p", "mobile": "9999999999"},
        "journey": {"from_station": "NDLS", "to_station": "BCT", "date": "2030-01-01"},
        "passengers": [{"name": "Test User", "age": 30, "gender": "M", "berth": "LB"}],
        "captcha": {"buster": {"extension_path": str(xpi)}},
    }), encoding="utf-8")

    cfg = load_config(str(cfg_file))
    assert str(xpi) in cfg.browser.addons


def test_config_no_autoload_when_missing(tmp_path):
    import json

    from ticket_booker.config import load_config

    cfg_file = tmp_path / "c.json"
    cfg_file.write_text(json.dumps({
        "irctc": {"username": "u", "password": "p", "mobile": "9999999999"},
        "journey": {"from_station": "NDLS", "to_station": "BCT", "date": "2030-01-01"},
        "passengers": [{"name": "Test User", "age": 30, "gender": "M", "berth": "LB"}],
        "captcha": {"buster": {"extension_path": str(tmp_path / "absent.xpi")}},
    }), encoding="utf-8")

    cfg = load_config(str(cfg_file))
    assert cfg.browser.addons == []


# --------------------------------------------------------------------------- #
# CLI + preflight
# --------------------------------------------------------------------------- #

def test_cli_buster_status(capsys, tmp_path):
    import json
    from argparse import Namespace

    from ticket_booker.cli import build_parser, cmd_buster

    args = build_parser().parse_args(["buster", "--status", "-c", str(tmp_path / "nope.json")])
    assert args.command == "buster"
    assert cmd_buster(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["icon_selector"] == "#solver-button"
    assert out["play_selector"] == PLAY_SELECTOR


def test_cli_buster_parses_install_and_try():
    from ticket_booker.cli import build_parser

    a = build_parser().parse_args(["buster", "--install"])
    assert a.install is True
    b = build_parser().parse_args(["buster", "--try", "https://example.com", "--native"])
    assert b.try_url == "https://example.com" and b.native is True


def test_preflight_reports_buster_native_path(tmp_path):
    import json

    from ticket_booker.config import load_config
    from ticket_booker.god.preflight import preflight

    cfg_file = tmp_path / "c.json"
    cfg_file.write_text(json.dumps({
        "irctc": {"username": "u", "password": "p", "mobile": "9999999999"},
        "journey": {"from_station": "NDLS", "to_station": "BCT", "date": "2030-01-01"},
        "passengers": [{"name": "Test User", "age": 30, "gender": "M", "berth": "LB"}],
        "captcha": {"buster": {"extension_path": str(tmp_path / "absent.xpi")}},
    }), encoding="utf-8")

    res = preflight(load_config(str(cfg_file)))
    check = next(c for c in res.checks if c["name"] == "captcha.buster")
    assert check["ok"] is True
    assert "native" in check["msg"]


def test_preflight_extension_mode_without_xpi_fails(tmp_path):
    import json

    from ticket_booker.config import load_config
    from ticket_booker.god.preflight import preflight

    cfg_file = tmp_path / "c.json"
    cfg_file.write_text(json.dumps({
        "irctc": {"username": "u", "password": "p", "mobile": "9999999999"},
        "journey": {"from_station": "NDLS", "to_station": "BCT", "date": "2030-01-01"},
        "passengers": [{"name": "Test User", "age": 30, "gender": "M", "berth": "LB"}],
        "captcha": {"buster": {"mode": "extension",
                               "extension_path": str(tmp_path / "absent.xpi")}},
    }), encoding="utf-8")

    res = preflight(load_config(str(cfg_file)))
    check = next(c for c in res.checks if c["name"] == "captcha.buster")
    assert check["ok"] is False
    assert "buster --install" in check["msg"]


def test_example_config_documents_buster():
    import json
    from pathlib import Path

    data = json.loads(
        (Path(__file__).resolve().parents[1] / "config.example.json").read_text(encoding="utf-8"))
    b = data["captcha"]["buster"]
    assert b["enabled"] is True
    assert b["mode"] == "auto"
    assert b["solve_checkbox"] is True
