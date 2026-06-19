#!/usr/bin/env python3
"""Menu-bar dropdown for the NBER digest.

Lives in the top-right menu bar. Shows a red dot + unread count when there are
papers you haven't opened, and a calm grey icon once everything is read. Each
paper is a dropdown item; expand it to read the 5-line summary, open it, or mark
it read. Reads digest.json (written by nber_digest.py) and refreshes when that
file changes, so the weekly Monday scrape updates the dropdown automatically.
"""

import json
import logging
import subprocess
import sys
import traceback
import webbrowser
from functools import partial
from pathlib import Path

import rumps
from AppKit import NSAttributedString, NSColor, NSForegroundColorAttributeName

HERE = Path(__file__).resolve().parent

logging.basicConfig(
    filename=str(HERE / "menubar.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
DIGEST_PATH = HERE / "digest.json"
PYTHON = HERE / ".venv" / "bin" / "python"
SCRAPER = HERE / "nber_digest.py"
POLL_SECONDS = 30


class NberMenuBar(rumps.App):
    def __init__(self) -> None:
        super().__init__("NBER", quit_button="Quit")
        self._mtime = 0.0
        self.papers: list[dict] = []
        self.load()
        rumps.Timer(self.poll, POLL_SECONDS).start()
        # Status item doesn't exist until the run loop starts; re-color shortly after.
        self._startup = rumps.Timer(self._on_startup, 1)
        self._startup.start()

    def _on_startup(self, timer) -> None:
        timer.stop()
        self.rebuild()

    # --- data -------------------------------------------------------------
    def load(self) -> None:
        if DIGEST_PATH.exists():
            self._mtime = DIGEST_PATH.stat().st_mtime
            self.papers = json.loads(DIGEST_PATH.read_text()).get("papers", [])
        else:
            self.papers = []
        self.rebuild()

    def save(self) -> None:
        data = {"papers": self.papers}
        if DIGEST_PATH.exists():
            data = json.loads(DIGEST_PATH.read_text())
            data["papers"] = self.papers
        DIGEST_PATH.write_text(json.dumps(data, indent=2))
        self._mtime = DIGEST_PATH.stat().st_mtime

    def poll(self, _timer) -> None:
        if DIGEST_PATH.exists() and DIGEST_PATH.stat().st_mtime != self._mtime:
            self.load()

    # --- rendering --------------------------------------------------------
    def rebuild(self) -> None:
        unread = sum(1 for p in self.papers if not p.get("read"))
        # Plain-text title (emoji in an NSStatusItem can render zero-width);
        # color carries the unread signal: red when unread, default when read.
        self.title = f"NBER {unread}" if unread else "NBER"
        self._color_title(unread)

    def _color_title(self, unread: int) -> None:
        try:
            button = self._nsapp.nsstatusitem.button()
        except Exception:
            button = None
        if button is None:
            return  # run loop hasn't created the status item yet
        if unread:
            attrs = {NSForegroundColorAttributeName: NSColor.systemRedColor()}
            button.setAttributedTitle_(
                NSAttributedString.alloc().initWithString_attributes_(self.title, attrs)
            )
        else:
            button.setAttributedTitle_(
                NSAttributedString.alloc().initWithString_(self.title)
            )

        self.menu.clear()
        if not self.papers:
            self.menu = ["No papers above threshold yet", None, self._refresh_item()]
            return

        items = []
        for p in sorted(self.papers, key=lambda x: x["score"], reverse=True):
            mark = "○" if p.get("read") else "●"
            parent = rumps.MenuItem(f"{mark}  [{p['score']}]  {p['title']}")
            for line in p["summary"].splitlines():
                if line.strip():
                    parent.add(rumps.MenuItem(line.strip()))  # no callback = greyed
            parent.add(rumps.separator)
            parent.add(rumps.MenuItem("Open paper ↗", callback=partial(self.open_paper, p["number"])))
            parent.add(rumps.MenuItem("Mark as read", callback=partial(self.mark_read, p["number"])))
            items.append(parent)

        items += [None, rumps.MenuItem("Mark all read", callback=self.mark_all_read), self._refresh_item()]
        self.menu = items

    def _refresh_item(self) -> rumps.MenuItem:
        return rumps.MenuItem("Refresh now", callback=self.refresh_now)

    # --- actions ----------------------------------------------------------
    def _find(self, number: str) -> dict | None:
        return next((p for p in self.papers if p["number"] == number), None)

    def open_paper(self, number, _sender) -> None:
        p = self._find(number)
        if p:
            if p.get("link"):
                webbrowser.open(p["link"])
            p["read"] = True
            self.save()
            self.rebuild()

    def mark_read(self, number, _sender) -> None:
        p = self._find(number)
        if p:
            p["read"] = True
            self.save()
            self.rebuild()

    def mark_all_read(self, _sender) -> None:
        for p in self.papers:
            p["read"] = True
        self.save()
        self.rebuild()

    def refresh_now(self, _sender) -> None:
        # Runs the scraper in the background; poll() picks up the new digest.json.
        subprocess.Popen([str(PYTHON), str(SCRAPER)])
        rumps.notification("NBER digest", "Refreshing…", "Scoring the latest NBER batch.")


if __name__ == "__main__":
    try:
        rumps.debug_mode(True)
        logging.info("starting; python=%s", sys.executable)
        NberMenuBar().run()
    except Exception:
        logging.error("crashed:\n%s", traceback.format_exc())
        raise
