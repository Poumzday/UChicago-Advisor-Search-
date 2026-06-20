#!/usr/bin/env python3
"""Menu-bar CTA #6 bus tab.

A bus-shaped menu-bar item listing the next three northbound #6 (Jackson Park
Express) arrivals at S Hyde Park Blvd & 53rd St — heading downtown past Michigan
& South Water. Refreshes only when you click the item (menuWillOpen). Live
predictions come from the CTA Bus Tracker API (real GPS minutes-away), keyed by
CTA_API_KEY in .env.
"""

import json
import logging
import os
import sys
import traceback
import urllib.parse
import urllib.request
from pathlib import Path

import rumps
from AppKit import NSColor, NSImage, NSImageLeft, NSImageSymbolConfiguration
from Foundation import NSObject

HERE = Path(__file__).resolve().parent
API = "https://www.ctabustracker.com/bustime/api/v2/getpredictions"
ROUTE = "6"
STOP_ID = "1521"          # S Hyde Park & 53rd Street, northbound
STOP_NAME = "Hyde Park & 53rd → downtown"
N_BUSES = 3

logging.basicConfig(
    filename=str(HERE / "bus.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def load_key() -> str:
    """Read CTA_API_KEY from environment or the sibling .env."""
    if os.environ.get("CTA_API_KEY"):
        return os.environ["CTA_API_KEY"]
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line.startswith("CTA_API_KEY=") and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def next_buses() -> list[str]:
    """Formatted lines for the next N northbound #6 arrivals at the stop."""
    key = load_key()
    if not key:
        return ["No CTA_API_KEY set"]
    qs = urllib.parse.urlencode({"key": key, "stpid": STOP_ID, "rt": ROUTE, "format": "json"})
    req = urllib.request.Request(f"{API}?{qs}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        resp = json.load(r)["bustime-response"]
    if "error" in resp:
        msg = resp["error"][0].get("msg", "error")
        # "No arrival times" is the normal no-service message, not a failure.
        return [msg if "no" not in msg.lower() else "No buses predicted right now"]

    seen = set()
    lines = []
    for p in resp.get("prd", []):
        vid = p.get("vid")
        if vid in seen:          # CTA sometimes returns duplicate rows
            continue
        seen.add(vid)
        cd = p.get("prdctdn", "")
        rel = "due" if cd in ("DUE", "0") else f"{cd} min"
        lines.append(f"{rel}   ·   to {p.get('des', '')}")
        if len(lines) == N_BUSES:
            break
    return lines or ["No buses predicted right now"]


class MenuDelegate(NSObject):
    """NSMenu delegate so we refresh exactly when the dropdown opens."""
    def menuWillOpen_(self, menu):
        if getattr(self, "cb", None):
            self.cb()


class BusMenuBar(rumps.App):
    def __init__(self) -> None:
        super().__init__("⋯", quit_button="Quit")
        self.header = rumps.MenuItem(STOP_NAME, callback=self._noop)
        self.rows = [rumps.MenuItem("…", callback=self._noop) for _ in range(N_BUSES)]
        self.menu = [self.header, None, *self.rows, None,
                     rumps.MenuItem("Refresh", callback=lambda _: self.refresh())]
        self._delegate = MenuDelegate.alloc().init()
        self._delegate.cb = self.refresh
        self._startup = rumps.Timer(self._on_startup, 1)
        self._startup.start()

    def _noop(self, _sender) -> None:
        pass

    def _on_startup(self, timer) -> None:
        timer.stop()
        self._set_icon()
        try:
            self._nsapp.nsstatusitem.menu().setDelegate_(self._delegate)
        except Exception:
            logging.error("could not set menu delegate:\n%s", traceback.format_exc())
        self.refresh()

    def refresh(self) -> None:
        try:
            lines = next_buses()
        except Exception:
            logging.error("refresh failed:\n%s", traceback.format_exc())
            lines = ["Bus times unavailable"]
        # Title = first bus's countdown (e.g. "3 min" or "due").
        first = lines[0].split("·")[0].strip() if lines else "—"
        self.title = first if first and "No " not in first and "unavailable" not in first else "#6"
        for i, item in enumerate(self.rows):
            item.title = lines[i] if i < len(lines) else "—"
        logging.info("refreshed: %s", lines)

    def _set_icon(self) -> None:
        try:
            button = self._nsapp.nsstatusitem.button()
        except Exception:
            return
        if button is None:
            return
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_("bus.fill", "CTA bus")
        if img is not None:
            try:
                cfg = NSImageSymbolConfiguration.configurationWithPaletteColors_(
                    [NSColor.controlTextColor()])
                img = img.imageWithSymbolConfiguration_(cfg)
            except Exception:
                pass
            img.setTemplate_(True)
            button.setImage_(img)
            button.setImagePosition_(NSImageLeft)


if __name__ == "__main__":
    try:
        logging.info("starting; python=%s", sys.executable)
        BusMenuBar().run()
    except Exception:
        logging.error("crashed:\n%s", traceback.format_exc())
        raise
