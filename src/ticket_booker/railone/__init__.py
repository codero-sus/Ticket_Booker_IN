"""RailOne (RailOne) support — roadmap + shared pieces.

RailOne is IRCTC's mobile super-app (Android/iOS). There is no public web
booking flow to automate with a browser, so full RailOne automation needs
either an Appium device farm or the app's private APIs (not public/stable).

Practical approach used by this repo:
  * For train tickets: the IRCTC web flow (irctc booker) books the exact same
    inventory RailOne sells — PNR/trains/fares are identical.
  * This package hosts the RailOne roadmap, deep-link helpers and (future)
    API/Appium adapters behind one interface.
"""

from .booker import RailOneBooker

__all__ = ["RailOneBooker"]
