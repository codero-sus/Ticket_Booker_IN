"""Launch the WebUI server and auto-open it in Chrome once ready."""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

log = logging.getLogger("ticket_booker.webui.launcher")


def find_chrome() -> str | None:
    """Locate a Chrome/Chromium binary. Chrome preferred, Chromium accepted."""
    for name in ("google-chrome", "google-chrome-stable", "chrome", "chromium",
                 "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    candidates = []
    if sys.platform == "darwin":
        candidates = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    elif sys.platform.startswith("win"):
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        lappdata = os.environ.get("LocalAppData", "")
        candidates = [
            str(Path(pf) / "Google/Chrome/Application/chrome.exe"),
            str(Path(pf + " (x86)") / "Google/Chrome/Application/chrome.exe"),
            str(Path(lappdata) / "Google/Chrome/Application/chrome.exe"),
        ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


def open_in_chrome(url: str, size: tuple[int, int] | None = None,
                   app_mode: bool = False) -> bool:
    """Open URL in Chrome (detached). Falls back to default browser.

    `size` opens a small popup window; `app_mode` drops the tab strip and
    address bar so it reads as a floating monitor. Returns True if Chrome
    itself was used."""
    chrome = find_chrome()
    if chrome:
        try:
            kwargs: dict = {}
            if os.name == "posix":
                kwargs["start_new_session"] = True
            else:  # Windows: fully detached
                kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0)
            args = [chrome]
            if app_mode:
                args.append(f"--app={url}")
            else:
                args.append(url)
            if size:
                args.append(f"--window-size={int(size[0])},{int(size[1])}")
                args.append(f"--window-position={int(size[2]) if len(size) > 2 else 40},"
                            f"{int(size[3]) if len(size) > 3 else 40}")
            profile_dir = Path(os.environ.get("TEMP", "/tmp")) / "tb-monitor-profile"
            if app_mode:
                args.append(f"--user-data-dir={profile_dir}")
            subprocess.Popen(args, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, **kwargs)
            log.info("🌐 Opened in Chrome: %s%s", url,
                     f" ({size[0]}x{size[1]})" if size else "")
            return True
        except Exception as exc:
            log.warning("Chrome launch failed (%s); using default browser.", exc)
    else:
        log.warning("Chrome not found; using default browser.")
    try:
        webbrowser.open(url)
    except Exception as exc:
        log.error("Could not open any browser: %s", exc)
    return False


def free_port(port: int, host: str = "127.0.0.1") -> int:
    """Return `port` if free, else the next free port above it."""
    for p in range(port, port + 50):
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    raise RuntimeError("No free port found.")


def wait_ready(url: str, timeout: int = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def parse_size(raw: str, default: tuple[int, int] = (430, 680)) -> tuple[int, int]:
    """Parse "430x680" into (430, 680)."""
    try:
        w, h = str(raw or "").lower().replace(" ", "").split("x")
        return max(240, int(w)), max(240, int(h))
    except Exception:
        return default


def start_background(port: int = 8765, host: str = "127.0.0.1",
                     config_path: str | None = None):
    """Start the WebUI on a daemon thread. Returns (server, base_url)."""
    from werkzeug.serving import make_server

    from .server import create_app

    port = free_port(port, host)
    app = create_app(config_path)
    server = make_server(host, port, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://{host}:{port}"
    wait_ready(url + "/api/health", timeout=10)
    return server, url


def open_monitor(base_url: str, size: str = "430x680") -> bool:
    """Open the small LIVE popup window pointed at /monitor."""
    w, h = parse_size(size)
    url = base_url.rstrip("/") + "/monitor"
    return open_in_chrome(url, size=(w, h, 40, 40), app_mode=True)


def serve(port: int = 8765, host: str = "127.0.0.1", open_browser: bool = True,
          config_path: str | None = None, block: bool = True):
    """Start the dashboard server, auto-open Chrome when ready, then serve."""
    from werkzeug.serving import make_server

    from .server import create_app

    port = free_port(port, host)
    app = create_app(config_path)
    server = make_server(host, port, app, threaded=True)
    url = f"http://{host}:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print("=" * 64)
    print(f"  🚂 Ticket_Booker_IN WebUI  →  {url}")
    print("=" * 64)
    if wait_ready(url + "/api/health"):
        print("  ✅ Server ready.")
        if open_browser:
            open_in_chrome(url)
            print("  🌐 Opening dashboard in Chrome...")
    else:
        print("  ⚠️ Server is slow to respond — try opening the URL manually.")
    print("  Press Ctrl+C to stop.\n")

    if not block:
        return server
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n  🛑 Stopping WebUI...")
    finally:
        server.shutdown()
