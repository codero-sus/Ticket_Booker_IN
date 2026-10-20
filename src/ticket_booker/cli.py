"""Command-line interface: ticket-booker <command> ..."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .utils import setup_logging


def _brutality_arg(raw: str) -> int:
    """argparse type: accept 4 or 'god of god of god of god' or 'god^god'."""
    from .god.algebra import BruteAlgebraError, parse_level_raw

    try:
        return parse_level_raw(raw)
    except BruteAlgebraError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _add_common(sp, config_required: bool = True):
    if config_required:
        sp.add_argument("--config", "-c", default="config.json", help="Config file (json/yaml). Default: config.json")
    sp.add_argument("--headless", action="store_true", help="Run browser headless (uses virtual display on servers).")
    sp.add_argument("--headed", action="store_true", help="Force visible browser (overrides config).")
    sp.add_argument("--brutality", type=_brutality_arg, default=None,
                    help="GOD dial: 1-5 BRUTE, 6-9 OMEGA, 10+ RADIOACTIVE, or an "
                         "EXPRESSION like 'god of god of god of god' (max INT64).")
    sp.add_argument("-v", "--verbose", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ticket-booker",
        description="Indian railway ticket booking automation (Camoufox + zero-touch captcha).",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init-config", help="Create a starter config.json from the bundled example.")
    s.add_argument("--out", default="config.json")
    s.add_argument("-v", "--verbose", action="store_true")

    s = sub.add_parser("doctor", help="Check dependencies, binaries and config health.")
    s.add_argument("--config", "-c", default=None)
    s.add_argument("-v", "--verbose", action="store_true")

    s = sub.add_parser("solve-captcha", help="Test the auto captcha solver on an image file (offline test).")
    s.add_argument("image", help="Path to a captcha image (png/jpg).")
    s.add_argument("--config", "-c", default=None, help="Optional config (uses its [captcha] section).")
    s.add_argument("-v", "--verbose", action="store_true")

    s = sub.add_parser("login", help="Log in to IRCTC and save the session (no booking).")
    _add_common(s)

    s = sub.add_parser("search", help="Login + search trains and capture the list (no booking).")
    _add_common(s)

    s = sub.add_parser("book", help="Full booking run (supports Tatkal race when configured).")
    _add_common(s)

    s = sub.add_parser("tatkal", help="book with Tatkal mode forced on.")
    _add_common(s)

    s = sub.add_parser(
        "auto",
        help="AUTOPILOT: hands-free booking - auto login, auto search, auto pay.",
    )
    s.add_argument("--cycles", type=int, default=0,
                   help="Full booking cycles before giving up (0 = use config).")
    s.add_argument("--small-window", dest="small_window", action="store_true",
                   default=None, help="Show the browser in a small watchable window.")
    s.add_argument("--no-small-window", dest="small_window", action="store_false",
                   help="Use the normal (large) browser window.")
    s.add_argument("--popup", action="store_true",
                   help="Also open the LIVE monitor as a small popup window.")
    s.add_argument("--monitor-size", default="",
                   help="Popup size, e.g. 430x680.")
    s.add_argument("--headless", action="store_true", help="Run without showing the browser.")
    s.add_argument("--brutality", "-b", default="", help="BRUTE ALGEBRA dial, e.g. \"void\".")
    s.add_argument("--config", "-c", default="config.json")
    s.add_argument("-v", "--verbose", action="store_true")

    s = sub.add_parser("railone", help="Show the RailOne roadmap / run via IRCTC fallback.")
    s.add_argument("--roadmap", action="store_true", help="Print roadmap and exit.")
    _add_common(s, config_required=False)
    s.add_argument("--config", "-c", default="config.json")

    s = sub.add_parser("tool", help="Run a BRUTE scraper tool: pnr|availability|schedule|fare|live.")
    s.add_argument("name", help="Tool name (pnr, availability, schedule, fare, live).")
    s.add_argument("--pnr", default="", help="PNR number (pnr tool).")
    s.add_argument("--train", default="", help="Train number override (schedule/live/availability).")
    s.add_argument("--station", default="", help="Station code filter (live tool).")
    s.add_argument("--heads", type=int, default=0, help="HYDRA heads 0(auto)-3 (OMEGA+, tools only).")
    _add_common(s)

    s = sub.add_parser("chaos", help="Run offline CHAOS drills (prove GOD survives).")
    s.add_argument("-v", "--verbose", action="store_true")

    s = sub.add_parser("preflight", help="Pre-flight checks before race day.")
    s.add_argument("--config", "-c", default="config.json")
    s.add_argument("-v", "--verbose", action="store_true")

    s = sub.add_parser("ascend", help="Evaluate a BRUTE ALGEBRA expression and ascend the dial.")
    s.add_argument("expression", nargs="?", default="god of god of god of god",
                   help="e.g. 'god of god of god of god' (default), 'god^god', "
                        "'ultimate brute god', or 9223372036854775807.")

    s = sub.add_parser(
        "buster",
        help="Buster bridge: install the extension, or click icon + PLAY on a URL.",
    )
    s.add_argument("--install", action="store_true",
                   help="Download Buster's signed .xpi from addons.mozilla.org.")
    s.add_argument("--status", action="store_true",
                   help="Show bridge status (extension on disk, mode, selectors).")
    s.add_argument("--try", dest="try_url", metavar="URL", default="",
                   help="Open URL, click the Buster icon then PLAY.")
    s.add_argument("--native", action="store_true",
                   help="Force the no-extension path (icon-click emulation).")
    s.add_argument("--config", "-c", default="config.json")
    s.add_argument("-v", "--verbose", action="store_true")

    s = sub.add_parser("webui", help="Launch the easy WebUI dashboard (auto-opens in Chrome).")
    s.add_argument("--port", type=int, default=8765, help="Port (default 8765, auto-bumps if busy).")
    s.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1).")
    s.add_argument("--no-open", action="store_true", help="Don't auto-open Chrome.")
    s.add_argument("--config", "-c", default="config.json", help="Config file the WebUI manages.")
    s.add_argument("-v", "--verbose", action="store_true")

    return p


def _apply_brutality(args, cfg) -> None:
    level = getattr(args, "brutality", None)
    if level:
        cfg.brute.level = int(level)


def _resolve_headless(args, cfg) -> bool:
    if args.headed:
        return False
    if args.headless:
        return True
    return cfg.browser.headless


def cmd_init_config(args) -> int:
    import logging

    log = logging.getLogger("ticket_booker.cli")
    out = Path(args.out)
    if out.exists():
        log.error("%s already exists; refusing to overwrite.", out)
        return 2
    # Find bundled example (repo root when running from source)
    candidates = [
        Path("config.example.json"),
        Path(__file__).resolve().parents[3] / "config.example.json",
    ]
    src = next((c for c in candidates if c.exists()), None)
    if src is None:
        log.error("config.example.json not found.")
        return 2
    out.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    log.info("Wrote %s — edit it with your journey + credentials.", out)
    print("\nNext: 1) edit config.json  2) ticket-booker doctor --config config.json  3) ticket-booker login -c config.json")
    return 0


def cmd_doctor(args) -> int:
    import logging

    log = logging.getLogger("ticket_booker.cli")
    ok = True

    def check(name: str, good: bool, hint: str = ""):
        nonlocal ok
        mark = "OK  " if good else "FAIL"
        if not good:
            ok = False
        print(f"[{mark}] {name}" + (f" — {hint}" if hint and not good else ""))

    print(f"ticket-booker {__version__}  |  python {sys.version.split()[0]}")
    print("-" * 60)

    # python packages
    import importlib.util

    for mod, pip_name in (
        ("camoufox", "camoufox"), ("playwright", "playwright"),
        ("pydantic", "pydantic"), ("PIL", "pillow"),
        ("cv2", "opencv-python-headless"), ("numpy", "numpy"),
        ("pytesseract", "pytesseract"), ("speech_recognition", "SpeechRecognition"),
        ("requests", "requests"), ("ntplib", "ntplib"), ("yaml", "pyyaml"),
    ):
        check(f"py: {pip_name}", importlib.util.find_spec(mod) is not None, f"pip install {pip_name}")
    for mod, pip_name in (("pydub", "pydub"), ("vosk", "vosk")):
        found = importlib.util.find_spec(mod) is not None
        print(f"[{'OK  ' if found else 'OPT '}] py: {pip_name} (optional)")

    # system binaries
    check("bin: tesseract (OCR)", shutil.which("tesseract") is not None, "sudo apt install tesseract-ocr")
    has_ffmpeg = shutil.which("ffmpeg") is not None
    print(f"[{'OK  ' if has_ffmpeg else 'OPT '}] bin: ffmpeg (reCAPTCHA audio mp3 decode)")

    # camoufox browser binaries
    try:
        from camoufox.pkgman import installed_verstr

        ver = installed_verstr()
        check(f"camoufox browser binaries ({ver})", True)
    except Exception:
        check("camoufox browser binaries", False, "run: camoufox fetch")

    # NTP reachability (quick)
    try:
        from .timing import measure_ntp_offset

        off = measure_ntp_offset(timeout=4)
        print(f"[OK  ] ntp sync (offset {off:+0.3f}s)")
    except Exception as exc:  # pragma: no cover
        print(f"[OPT ] ntp sync unreachable ({exc})")

    # config
    if args.config:
        try:
            from .config import load_config

            cfg = load_config(args.config)
            check(f"config {args.config}", True)
            j = cfg.journey
            print(f"       journey: {j.from_station}->{j.to_station} {j.date} "
                  f"train={j.train_no or 'any'} {j.class_code}/{j.quota} pax={len(cfg.passengers)}")
            solvers = []
            from .captcha.manager import AutoCaptcha

            ac = AutoCaptcha(cfg.captcha)
            for s in ac.solvers:
                solvers.append(f"{s.name}:{'ready' if s.available() else 'missing'}")
            print(f"       captcha solvers: {', '.join(solvers) or 'none (manual mode)'}")
            gcfg = getattr(cfg.captcha, "gemini", None)
            if gcfg is not None and getattr(gcfg, "enabled", False):
                g_key = "key set" if (gcfg.api_key or "").strip() else "no key"
                g_nano = "on-device (attached at launch)" if gcfg.mode in ("auto", "nano") else "off"
                print(f"       gemini: model={gcfg.model} api={g_key} "
                      f"nano={g_nano} repair_ocr={gcfg.repair_ocr}")
            bcfg = getattr(cfg.captcha, "buster", None)
            if bcfg is not None:
                from .captcha.buster import extension_installed as _ext_ok

                print(f"       buster: mode={bcfg.mode} "
                      f"extension={'installed' if _ext_ok(bcfg) else 'native only'} "
                      f"(icon #solver-button -> PLAY)")
        except Exception as exc:
            check(f"config {args.config}", False, str(exc)[:220])

    try:
        from .god.apotheosis import apotheosis_title
        from .god.session_vault import vault_status
        mem_keys, lvl = 0, None
        _mp = Path("./profiles/selector_memory.json")
        if _mp.exists():
            try:
                mem_keys = len(json.loads(_mp.read_text(encoding="utf-8") or "{}"))
            except Exception:
                mem_keys = 0
        if args.config and Path(args.config).exists():
            try:
                from .config import load_config as _lc
                lvl = _lc(args.config).brute.level
            except Exception:
                lvl = None
        print(f"GOD: level={lvl} ({apotheosis_title(lvl) if lvl else 'no config'}) | "
              f"memory_keys={mem_keys} | vault={vault_status().get('count', 0)} cookies")
    except Exception as exc:
        print(f"GOD: status unavailable ({exc})")
    print("-" * 60)
    print("doctor: " + ("ALL GOOD" if ok else "issues found (see FAIL lines)"))
    return 0 if ok else 1


def cmd_solve_captcha(args) -> int:
    import logging

    log = logging.getLogger("ticket_booker.cli")
    img_path = Path(args.image)
    if not img_path.exists():
        log.error("Image not found: %s", img_path)
        return 2
    if args.config:
        from .config import load_config

        cfg_captcha = load_config(args.config).captcha
    else:
        from .config import CaptchaCfg

        cfg_captcha = CaptchaCfg()
    from .captcha.manager import AutoCaptcha

    ac = AutoCaptcha(cfg_captcha)
    res = ac.solve_text_image(img_path.read_bytes())
    print(json.dumps({"text": res.text, "confidence": round(res.confidence, 1), "solver": res.solver}))
    return 0 if res.ok else 1


def cmd_buster(args) -> int:
    """Install / inspect / fire the Buster bridge."""
    from .captcha.buster import (
        AMO_XPI_URL,
        BusterSolver,
        buster_xpi_path,
        download_extension,
        extension_installed,
    )
    from .config import load_config

    cfg = None
    try:
        cfg = load_config(args.config)
    except Exception as exc:
        if args.try_url:
            print(f"cannot open a browser without a valid config: {exc}")
            return 2
        from .config import BusterCfg

        print(f"note: {args.config} not usable ({exc}); showing defaults", file=sys.stderr)

    bcfg = cfg.captcha.buster if cfg is not None else BusterCfg()
    xpi = buster_xpi_path(bcfg)

    if args.install:
        print(f"Downloading Buster extension from {AMO_XPI_URL}")
        try:
            path = download_extension(xpi)
        except Exception as exc:
            print(f"FAILED: {exc}")
            print("Manual option: download the .xpi in your browser and save it to")
            print(f"  {xpi}")
            return 1
        print(f"OK: {path} ({path.stat().st_size:,} bytes)")
        print('It will be loaded automatically on the next run (browser.addons).')
        return 0

    if args.try_url:
        from .browser import launch_browser

        if not args.native and not extension_installed(bcfg):
            print(f"No extension at {xpi} - running the native path.")
            print("Run `ticket-booker buster --install` for the real extension.")
        solver = BusterSolver(
            mode="native" if args.native else bcfg.mode,
            timeout=bcfg.timeout,
            max_attempts=bcfg.max_attempts,
            solve_checkbox=bcfg.solve_checkbox,
            language=bcfg.language,
        )
        with launch_browser(cfg.browser, cfg.browser.headless) as session:
            page = session.page
            page.goto(args.try_url, wait_until="domcontentloaded")
            solver.set_page(page)
            print(json.dumps(solver.status(), indent=2))
            print("Clicking the Buster icon (or emulating it)...")
            result = solver.solve(page)
            print(json.dumps(result.__dict__, indent=2))
            return 0 if result.solved else 1

    print(json.dumps(_buster_info(bcfg), indent=2))
    return 0


def _buster_info(bcfg) -> dict:
    """The status dict `buster --status` prints."""
    from .captcha.buster import PLAY_SELECTOR, buster_xpi_path, extension_installed

    return {
        "enabled": bcfg.enabled,
        "mode": bcfg.mode,
        "extension_path": str(buster_xpi_path(bcfg)),
        "extension_installed": extension_installed(bcfg),
        "icon_selector": "#solver-button",
        "play_selector": PLAY_SELECTOR,
    }


def _load_cfg(args):
    from .config import load_config

    return load_config(args.config)


def cmd_login(args) -> int:
    from .irctc.booker import IRCTCBooker

    cfg = _load_cfg(args)
    _apply_brutality(args, cfg)
    ok = IRCTCBooker(cfg, headless=_resolve_headless(args, cfg)).login_only()
    print("LOGIN OK" if ok else "LOGIN FAILED")
    return 0 if ok else 1


def cmd_search(args) -> int:
    from .irctc.booker import IRCTCBooker

    cfg = _load_cfg(args)
    _apply_brutality(args, cfg)
    ok = IRCTCBooker(cfg, headless=_resolve_headless(args, cfg)).search_only()
    return 0 if ok else 1


def cmd_book(args, force_tatkal: bool = False) -> int:
    from .irctc.booker import IRCTCBooker

    cfg = _load_cfg(args)
    _apply_brutality(args, cfg)
    if force_tatkal:
        cfg.tatkal.enabled = True
        if cfg.journey.quota == "GN":
            cfg.journey.quota = "TQ"
    res = IRCTCBooker(cfg, headless=_resolve_headless(args, cfg)).book()
    print(("SUCCESS: " if res.success else "FAILED: ") + res.message)
    return 0 if res.success else 1


def cmd_railone(args) -> int:
    from .railone.booker import RailOneBooker

    if args.roadmap or not Path(args.config).exists():
        print(RailOneBooker.roadmap())
        return 0
    cfg = _load_cfg(args)
    res = RailOneBooker(cfg).book()
    print(("SUCCESS: " if res.success else "FAILED: ") + res.message)
    return 0 if res.success else 1


def cmd_tool(args) -> int:
    from .tools import TOOLS

    name = args.name.strip().lower()
    if name not in TOOLS:
        print(f"Unknown tool {name!r}. Choose from: {', '.join(TOOLS)}")
        for k, (_fn, desc) in TOOLS.items():
            print(f"  {k:12s} {desc}")
        return 2
    fn, _desc = TOOLS[name]
    cfg = _load_cfg(args)
    _apply_brutality(args, cfg)
    if getattr(args, "heads", None):
        cfg.brute.hydra_heads = max(0, min(3, int(args.heads)))
    headless = _resolve_headless(args, cfg)
    kwargs: dict = {"headless": headless}
    if name == "pnr":
        if not args.pnr:
            print("Usage: ticket-booker tool pnr --pnr 1234567890 -c config.json")
            return 2
        kwargs["pnr"] = args.pnr
    elif name in ("schedule", "live"):
        if not args.train:
            print(f"Usage: ticket-booker tool {name} --train 12430 [--station NDLS] -c config.json")
            return 2
        kwargs["train_no"] = args.train
        if name == "live":
            kwargs["station"] = args.station
    elif name == "availability":
        if args.train:
            kwargs["train_no"] = args.train
    res = fn(cfg, **kwargs)
    print(("SUCCESS: " if res.ok else "FAILED: ") + res.message)
    if res.report_path:
        print(f"Report: {res.report_path}")
    return 0 if res.ok else 1


def cmd_chaos(args) -> int:
    from .god.chaos import run_drills

    results = run_drills()
    print('DRILL'.ljust(28) + 'RESULT  DETAIL')
    ok_all = True
    for r in results:
        ok_all &= r.ok
        mark = 'PASS' if r.ok else 'FAIL'
        print(r.name.ljust(28) + ' ' + mark.ljust(6) + '  ' + r.detail)
    print("CHAOS: " + ("GOD SURVIVES" if ok_all else "GOD WOUNDED - see FAIL"))
    return 0 if ok_all else 1


def cmd_preflight(args) -> int:
    from .god.preflight import preflight

    res = preflight(_load_cfg(args))
    for c in res.checks:
        mark = "OK  " if c["ok"] else ("WARN" if c["level"] == "warn" else "FAIL")
        print('[' + mark + '] ' + c['name'] + ': ' + c['msg'])
    print("PREFLIGHT: " + ("CLEARED FOR TAKEOFF" if res.ok else "DO NOT FLY - fix FAILs"))
    return 0 if res.ok else 1


def cmd_ascend(args) -> int:
    from .god.algebra import BruteAlgebraError
    from .god.apotheosis import report

    try:
        r = report(args.expression)
    except BruteAlgebraError as exc:
        print(f"BRUTE ALGEBRA ERROR: {exc}")
        return 2
    print("APOTHEOSIS - TOO MUCH BRUTE")
    print("-" * 60)
    print(f"expression : {r['expression']}")
    print(f"dial       : {r['level_text']}" + ("  (INT64 MAX)" if r["at_max"] else ""))
    print(f"tier       : {r['tier']}")
    print(f"title      : {r['title']}")
    print(f"depth      : {r['god_depth']} OF THE layers "
          f"({r['repeat_count']}x ULTIMATE BRUTE GOD)")
    print(f"warcry     : {r['warcry']}")
    try:
        from .god.genome import Genome

        s = Genome("./profiles/genome.json").summary()
        if s["plays"]:
            board = ", ".join(f"{x['arm']} {x['wins']}/{x['plays']}"
                              for x in s["leaderboard"])
            print(f"genome     : {board}")
        else:
            print("genome     : fresh (no strategy DNA yet)")
    except Exception:
        pass
    print("-" * 60)
    print(("VERDICT: THE DIAL IS MAXED - " if r["at_max"] else "VERDICT: ")
          + r["title"])
    return 0


def cmd_auto(args) -> int:
    """Hands-free booking: auto login, auto search, auto pay, live popup."""
    from .config import load_config
    from .irctc.autopilot import Autopilot

    cfg = load_config(args.config)

    raw = getattr(args, "brutality", "") or ""
    if raw:
        from .god.algebra import parse_level_raw

        cfg.brute.level = parse_level_raw(raw)
    if getattr(args, "cycles", 0):
        cfg.pilot.max_cycles = max(1, int(args.cycles))

    # Watchable by default: that is the point of AUTOPILOT.
    small = getattr(args, "small_window", None)
    cfg.browser.small_window = True if small is None else bool(small)

    print("=" * 64)
    print("  🤖 AUTOPILOT - hands-free booking")
    print(f"  {cfg.journey.from_station} -> {cfg.journey.to_station} on "
          f"{cfg.journey.date} | {cfg.journey.class_code}/{cfg.journey.quota} | "
          f"{len(cfg.passengers)} pax")
    print(f"  cycles={cfg.pilot.max_cycles}  small_window={cfg.browser.small_window} "
          f"  auto_submit={cfg.payment.auto_submit or cfg.pilot.auto_submit}")
    print("  No prompts. No clicking. Watch it in the monitor window.")
    print("=" * 64)

    if getattr(args, "popup", False):
        try:
            from .webui import launcher

            _server, url = launcher.start_background(config_path=args.config)
            size = getattr(args, "monitor_size", "") or cfg.pilot.monitor_size
            launcher.open_monitor(url, size)
            print(f"  🪟 LIVE monitor: {url}/monitor ({size})")
        except Exception as exc:
            print(f"  (monitor popup unavailable: {exc})")

    report = Autopilot(cfg, headless=bool(getattr(args, "headless", False))).run()
    print(json.dumps(report.as_dict(), indent=2))
    return 0 if report.ok else 1


def cmd_webui(args) -> int:
    from .webui.launcher import serve

    serve(port=args.port, host=args.host, open_browser=not args.no_open,
          config_path=args.config)
    return 0


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    setup_logging(getattr(args, "verbose", False))
    code = {
        "init-config": cmd_init_config,
        "doctor": cmd_doctor,
        "solve-captcha": cmd_solve_captcha,
        "login": cmd_login,
        "search": cmd_search,
        "book": lambda a: cmd_book(a, False),
        "tatkal": lambda a: cmd_book(a, True),
        "railone": cmd_railone,
        "tool": cmd_tool,
        "webui": cmd_webui,
        "chaos": cmd_chaos,
        "preflight": cmd_preflight,
        "ascend": cmd_ascend,
        "buster": cmd_buster,
        "auto": cmd_auto,
    }[args.command](args)
    sys.exit(code or 0)
