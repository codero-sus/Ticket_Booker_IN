"""Easy WebUI: one command -> local dashboard auto-opened in Chrome.

Run: `ticket-booker webui`
Then: click buttons for booking + all brute tools, watch live logs, test the
captcha solver, edit config — no terminal needed after launch.
"""

from .launcher import find_chrome, serve
from .server import create_app

__all__ = ["create_app", "serve", "find_chrome"]
