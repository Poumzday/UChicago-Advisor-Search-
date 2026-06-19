#!/usr/bin/env python3
"""Menu-bar dropdown for the NBER digest.

Lives in the top-right menu bar. The title turns red with a hazard symbol while
there are unread papers, and goes back to a calm default once everything is read.
Each paper is a single dropdown item; clicking it opens a clean one-page summary
(overview, methods, findings, why it's relevant to you) with a link to the paper,
and marks it read. Reads digest.json (written by nber_digest.py) and refreshes
when that file changes, so the weekly Monday scrape updates the dropdown.
"""

import html
import json
import logging
import subprocess
import sys
import traceback
import webbrowser
from functools import partial
from pathlib import Path

import rumps
from AppKit import (
    NSAttributedString,
    NSColor,
    NSForegroundColorAttributeName,
    NSImage,
    NSImageLeft,
    NSImageSymbolConfiguration,
)

HERE = Path(__file__).resolve().parent

logging.basicConfig(
    filename=str(HERE / "menubar.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
DIGEST_PATH = HERE / "digest.json"
PAGES_DIR = HERE / "pages"
PYTHON = HERE / ".venv" / "bin" / "python"
SCRAPER = HERE / "nber_digest.py"
POLL_SECONDS = 30


class NberMenuBar(rumps.App):
    def __init__(self) -> None:
        super().__init__("NBER", quit_button="Quit")
        self._hazard = None
        self._mtime = 0.0
        self.papers: list[dict] = []
        self.load()
        rumps.Timer(self.poll, POLL_SECONDS).start()
        # Status item doesn't exist until the run loop starts; re-style shortly after.
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
        self.title = f"NBER {unread}" if unread else "NBER"

        self.menu.clear()
        if not self.papers:
            self.menu = ["No papers above threshold yet", None,
                         rumps.MenuItem("Refresh now", callback=self.refresh_now)]
        else:
            items = []
            for p in sorted(self.papers, key=lambda x: x["score"], reverse=True):
                mark = "○" if p.get("read") else "●"
                label = f"{mark}  [{p['score']}]  {p['title']}"
                items.append(rumps.MenuItem(label, callback=partial(self.open_paper, p["number"])))
            items += [None,
                      rumps.MenuItem("Mark all read", callback=self.mark_all_read),
                      rumps.MenuItem("Refresh now", callback=self.refresh_now)]
            self.menu = items

        self._style_title(unread)

    def _style_title(self, unread: int) -> None:
        """Red title + hazard symbol when unread; default appearance when read."""
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
            button.setImage_(self._hazard_image())
            button.setImagePosition_(NSImageLeft)
        else:
            button.setAttributedTitle_(
                NSAttributedString.alloc().initWithString_(self.title)
            )
            button.setImage_(None)

    def _hazard_image(self):
        if self._hazard is None:
            img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "exclamationmark.triangle.fill", "unread NBER papers"
            )
            if img is not None:
                try:
                    cfg = NSImageSymbolConfiguration.configurationWithPaletteColors_(
                        [NSColor.systemRedColor()]
                    )
                    img = img.imageWithSymbolConfiguration_(cfg)
                except Exception:
                    pass
                img.setTemplate_(False)  # keep our red tint instead of menu-bar tint
            self._hazard = img
        return self._hazard

    # --- actions ----------------------------------------------------------
    def _find(self, number: str) -> dict | None:
        return next((p for p in self.papers if p["number"] == number), None)

    def open_paper(self, number, _sender) -> None:
        p = self._find(number)
        if not p:
            return
        webbrowser.open(self._render_page(p).as_uri())
        p["read"] = True
        self.save()
        self.rebuild()

    def _render_page(self, p: dict) -> Path:
        """Write a one-page HTML summary for paper p and return its path."""
        PAGES_DIR.mkdir(exist_ok=True)
        e = html.escape

        def section(heading: str, body: str) -> str:
            if not body:
                return ""
            return f"<h2>{e(heading)}</h2><p>{e(body)}</p>"

        body = (
            section("Overview", p.get("overview") or p.get("summary", ""))
            + section("Methods", p.get("methods", ""))
            + section("Findings", p.get("findings", ""))
        )

        # Clickable author chips: click a name to reveal its affiliation.
        authors = p.get("authors_aff")
        if authors:
            chips = []
            for a in authors:
                name = e(a.get("name", ""))
                aff = e(a.get("affiliation") or "Affiliation not listed")
                chips.append(
                    f'<span class="author" onclick="this.nextElementSibling'
                    f'.classList.toggle(\'show\')">{name}</span>'
                    f'<span class="aff">{aff}</span>'
                )
            authors_html = " &nbsp;·&nbsp; ".join(chips)
            hint = '<p class="hint">Click an author to see their affiliation.</p>'
        else:
            authors_html = e(p.get("authors", ""))
            hint = ""

        link = e(p.get("link", ""))
        doc = f"""<!doctype html><html><head><meta charset="utf-8">
<title>{e(p['title'])}</title>
<style>
 body {{ font: 16px/1.6 -apple-system, system-ui, sans-serif; max-width: 720px;
        margin: 48px auto; padding: 0 24px; color: #1d1d1f; background: #fbfbfd; }}
 .score {{ display:inline-block; background:#b3261e; color:#fff; font-weight:600;
           border-radius:6px; padding:2px 10px; font-size:14px; }}
 h1 {{ font-size: 26px; line-height:1.25; margin: 12px 0 6px; }}
 .authors {{ margin: 0; }}
 .author {{ color:#0071e3; cursor:pointer; text-decoration: underline dotted; }}
 .aff {{ display:none; margin-left:6px; font-size:13px; color:#fff;
         background:#3a3a3c; padding:1px 8px; border-radius:10px; }}
 .aff.show {{ display:inline-block; }}
 .hint {{ color:#6e6e73; font-size:13px; margin: 4px 0 0; }}
 h2 {{ font-size: 15px; text-transform: uppercase; letter-spacing: .04em;
       color:#6e6e73; margin: 28px 0 6px; }}
 p {{ margin: 0; }}
 a.btn {{ display:inline-block; margin-top:32px; background:#0071e3; color:#fff;
          text-decoration:none; padding:10px 18px; border-radius:8px; font-weight:600; }}
</style></head><body>
<span class="score">relevance {p['score']}</span>
<h1>{e(p['title'])}</h1>
<p class="authors">{authors_html}</p>
{hint}
{body}
<a class="btn" href="{link}">Open paper on NBER ↗</a>
</body></html>"""
        out = PAGES_DIR / f"{p['number']}.html"
        out.write_text(doc)
        return out

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
