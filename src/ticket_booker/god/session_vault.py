"""Session vault — login ONCE, transplant the session into fresh heads.

After any successful IRCTC login, cookies are saved (base64-obscured) to
`./profiles/session_vault.json`. Fresh browsers (god relaunch rounds, HYDRA
heads) load them for instant login without burning another captcha.

NOTE: base64 is obfuscation, NOT encryption. The vault is gitignored — treat
it like a password and never share it.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import tempfile
import time
from pathlib import Path

log = logging.getLogger("ticket_booker.god.vault")

VAULT_PATH = "./profiles/session_vault.json"


def _vault_file(path: str | Path | None) -> Path:
    return Path(path or VAULT_PATH)


def save_vault(context, path: str | Path | None = None) -> int:
    """Persist context cookies. Returns count saved (0 on any failure)."""
    try:
        cookies = [c for c in (context.cookies() or []) if isinstance(c, dict) and c.get("name")]
        if not cookies:
            return 0
        payload = {"saved_on": time.strftime("%Y-%m-%d %H:%M:%S"), "cookies": cookies}
        blob = base64.b64encode(json.dumps(payload).encode()).decode()
        f = _vault_file(path)
        f.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(f.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(blob)
        os.replace(tmp, f)
        log.info("🧬 Vault: saved %d cookies.", len(cookies))
        return len(cookies)
    except Exception as exc:
        log.debug("vault save skipped: %s", exc)
        return 0


def load_vault(context, path: str | Path | None = None) -> int:
    """Transplant vault cookies into a context. Returns count loaded."""
    f = _vault_file(path)
    try:
        if not f.exists():
            return 0
        payload = json.loads(base64.b64decode(f.read_text(encoding="utf-8").strip()).decode())
        cookies = payload.get("cookies") or []
    except Exception as exc:
        log.debug("vault unreadable, starting fresh: %s", exc)
        return 0
    now = time.time()
    loaded = 0
    for c in cookies:
        try:
            exp = c.get("expires", -1)
            if isinstance(exp, (int, float)) and exp > 0 and exp < now:
                continue  # stale cookie, skip
            context.add_cookies([c])
            loaded += 1
        except Exception:
            continue
    if loaded:
        log.info("🧬 Vault: transplanted %d cookies.", loaded)
    return loaded


def vault_status(path: str | Path | None = None) -> dict:
    """Offline-safe vault summary for doctor/WebUI."""
    f = _vault_file(path)
    try:
        if not f.exists():
            return {"exists": False, "count": 0, "saved_on": ""}
        payload = json.loads(base64.b64decode(f.read_text(encoding="utf-8").strip()).decode())
        cookies = payload.get("cookies") or []
        return {"exists": True, "count": len(cookies),
                "saved_on": str(payload.get("saved_on", ""))}
    except Exception:
        return {"exists": bool(f.exists()), "count": 0, "saved_on": ""}
