#!/usr/bin/env python3
"""Menu-bar dropdown for the NBER digest.

Lives in the top-right menu bar. Shows a red dot + unread count when there are
papers you haven't opened, and a calm grey icon once everything is read. Each
paper is a dropdown item; expand it to read the 5-line summary, open it, or mark
it read. Reads digest.json (written by nber_digest.py) and refreshes when that
file changes, so the weekly Monday scrape updates the dropdown automatically.
"""

import json
import subprocess
import webbrowser
from functools import partial
from pathlib import Path

import rumps

HERE = Path(__file__).resolve().parent
DIGEST_PATH = HERE / "digest.json"
PYTHON = HERE / ".venv" / "bin" / "python"
SCRAPER = HERE / "nber_digest.py"
POLL_SECONDS = 30

TITLE_UNREAD = "🔴 NBER"   # attention color until you click in
TITLE_READ = "⚪ NBER"     # calm once everything is read
TITLE_EMPTY = "⚪ NBER"


class NberMenuBar(rumps.App):
    def __init__(self) -> None:
        super().__init__(TITLE_EMPTY, quit_button="Quit")
        self._mtime = 0.0
        self.papers: list[dict] = []
        self.load()
        rumps.Timer(self.poll, POLL_SECONDS).start()

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
        self.title = (
            f"{TITLE_UNREAD} {unread}" if unread else
            (TITLE_READ if self.papers else TITLE_EMPTY)
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
    NberMenuBar().run()
