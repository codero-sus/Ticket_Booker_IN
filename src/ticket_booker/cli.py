"""Command-line interface: ticket-booker <command> ..."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .utils import setup_logging


def _add_common(sp, config_required: bool = True):
    if config_required:
        sp.add_argument("--config", "-c", default="config.json", help="Config file (json/yaml). Default: config.json")
    sp.add_argument("--headless", action="store_true", help="Run browser headless (uses virtual display on servers).")
    sp.add_argument("--headed", action="store_true", help="Force visible browser (overrides config).")
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

    s = sub.add_parser("railone", help="Show the RailOne roadmap / run via IRCTC fallback.")
    s.add_argument("--roadmap", action="store_true", help="Print roadmap and exit.")
    _add_common(s, config_required=False)
    s.add_argument("--config", "-c", default="config.json")

    return p


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
        except Exception as exc:
            check(f"config {args.config}", False, str(exc)[:220])

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


def _load_cfg(args):
    from .config import load_config

    return load_config(args.config)


def cmd_login(args) -> int:
    from .irctc.booker import IRCTCBooker

    cfg = _load_cfg(args)
    ok = IRCTCBooker(cfg, headless=_resolve_headless(args, cfg)).login_only()
    print("LOGIN OK" if ok else "LOGIN FAILED")
    return 0 if ok else 1


def cmd_search(args) -> int:
    from .irctc.booker import IRCTCBooker

    cfg = _load_cfg(args)
    ok = IRCTCBooker(cfg, headless=_resolve_headless(args, cfg)).search_only()
    return 0 if ok else 1


def cmd_book(args, force_tatkal: bool = False) -> int:
    from .irctc.booker import IRCTCBooker

    cfg = _load_cfg(args)
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
    }[args.command](args)
    sys.exit(code or 0)
