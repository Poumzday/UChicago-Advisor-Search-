#!/usr/bin/env python3
"""Single menu-bar item combining Bus, Weather, and NBER into one dropdown.

A notched MacBook hides the status icons nearest the notch when space is tight,
so three separate items got clipped. This consolidates them into ONE menu-bar
item (one slot, never clipped) with three sections in the dropdown:

  🚌 Bus      — next 3 northbound #6 arrivals at Hyde Park & 53rd (live, on click)
  ☀ Weather  — current + high/low + next 10 hours (refreshed on click / hourly)
  📰 NBER     — papers above threshold; click one for its 1-page summary

The menu-bar title shows the next bus countdown, turning red with a hazard mark
when there are unread NBER papers. Bus + weather refresh when you open the menu;
NBER updates itself when the weekly scrape rewrites digest.json.
"""

import html
import json
import logging
import traceback
import webbrowser
from functools import partial
from pathlib import Path

import rumps
from AppKit import (
    NSAttributedString, NSColor, NSForegroundColorAttributeName,
    NSImage, NSImageLeft, NSImageSymbolConfiguration,
)

# Data logic lives in the per-tab modules; we reuse their pure functions.
# Also reuse bus_app's NSMenu delegate class (ObjC class names are global —
# redefining one here would collide at the runtime level).
from weather_app import fetch_weather, hourly_rows, condition, symbol_image, is_night
from bus_app import next_buses, MenuDelegate

HERE = Path(__file__).resolve().parent
DIGEST_PATH = HERE / "digest.json"
PAGES_DIR = HERE / "pages"
N_WEATHER_ROWS = 5

logging.basicConfig(filename=str(HERE / "dashboard.log"), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")


class Dashboard(rumps.App):
    def __init__(self) -> None:
        super().__init__("…", quit_button="Quit")
        self.papers: list[dict] = []
        self._digest_mtime = 0.0

        # --- fixed skeleton we update in place ---
        self.bus_rows = [rumps.MenuItem("…", callback=self._noop) for _ in range(3)]
        self.bus = rumps.MenuItem("🚌  Bus — Hyde Park & 53rd → downtown")
        for r in self.bus_rows:
            self.bus.add(r)

        self.wx_now = rumps.MenuItem("…", callback=self._noop)
        self.wx_hilo = rumps.MenuItem("…", callback=self._noop)
        self.wx_city = rumps.MenuItem("…", callback=self._noop)
        self.wx_rows = [rumps.MenuItem("…", callback=self._noop) for _ in range(N_WEATHER_ROWS)]
        self.weather = rumps.MenuItem("☀  Weather")
        for it in (self.wx_now, self.wx_hilo, self.wx_city,
                   rumps.MenuItem("Next 10 hours", callback=self._noop), *self.wx_rows):
            self.weather.add(it)

        self.nber = rumps.MenuItem("📰  NBER digest")
        self.nber.add(rumps.MenuItem("Loading…", callback=self._noop))  # creates submenu NSMenu

        self.menu = [self.bus, self.weather, self.nber, None,
                     rumps.MenuItem("Refresh", callback=lambda _: self.refresh())]

        self._delegate = MenuDelegate.alloc().init()
        self._delegate.cb = self.refresh
        rumps.Timer(self._poll_digest, 30).start()  # pick up weekly NBER updates
        self._startup = rumps.Timer(self._on_startup, 1)
        self._startup.start()

    def _noop(self, _sender) -> None:
        pass

    def _on_startup(self, timer) -> None:
        timer.stop()
        try:
            self._nsapp.nsstatusitem.menu().setDelegate_(self._delegate)
        except Exception:
            logging.error("delegate:\n%s", traceback.format_exc())
        self._load_digest()
        self.refresh()

    # ---------- refresh (on menu open) ----------
    def refresh(self) -> None:
        next_bus = self._refresh_bus()
        self._refresh_weather()
        self._poll_digest(None)
        self._set_title(next_bus)
        logging.info("refreshed; next_bus=%s", next_bus)

    def _refresh_bus(self) -> str:
        try:
            lines = next_buses()
        except Exception:
            logging.error("bus:\n%s", traceback.format_exc())
            lines = ["Bus times unavailable"]
        for i, r in enumerate(self.bus_rows):
            r.title = lines[i] if i < len(lines) else "—"
        first = lines[0].split("·")[0].strip() if lines else ""
        return first if first and "No " not in first and "unavailable" not in first else ""

    def _refresh_weather(self) -> None:
        try:
            wx = fetch_weather()
        except Exception:
            logging.error("weather:\n%s", traceback.format_exc())
            self.wx_now.title = "Weather unavailable"
            return
        cur = wx["current"]
        _, label, _ = condition(cur["weather_code"], is_night(cur["time"], wx["daily"]))
        self.wx_now.title = f"{label} · now {round(cur['temperature_2m'])}°F"
        self.wx_hilo.title = (f"High {round(wx['daily']['temperature_2m_max'][0])}°F"
                              f"    Low {round(wx['daily']['temperature_2m_min'][0])}°F")
        self.wx_city.title = wx["city"]
        rows = hourly_rows(wx)
        for i, item in enumerate(self.wx_rows):
            if i < len(rows):
                text, sym, col = rows[i]
                item.title = text
                img = symbol_image(sym, col, size=14)
                if img is not None:
                    item._menuitem.setImage_(img)
            else:
                item.title = ""

    # ---------- NBER ----------
    def _poll_digest(self, _timer) -> None:
        if DIGEST_PATH.exists() and DIGEST_PATH.stat().st_mtime != self._digest_mtime:
            self._load_digest()

    def _load_digest(self) -> None:
        if DIGEST_PATH.exists():
            self._digest_mtime = DIGEST_PATH.stat().st_mtime
            self.papers = json.loads(DIGEST_PATH.read_text()).get("papers", [])
        else:
            self.papers = []
        self._rebuild_nber()
        self._set_title(None, keep_bus=True)

    def _rebuild_nber(self) -> None:
        self.nber.clear()
        if not self.papers:
            self.nber.add(rumps.MenuItem("No papers above threshold", callback=self._noop))
            return
        for p in sorted(self.papers, key=lambda x: x["score"], reverse=True):
            mark = "○" if p.get("read") else "●"
            self.nber.add(rumps.MenuItem(f"{mark}  [{p['score']}]  {p['title']}",
                                         callback=partial(self.open_paper, p["number"])))
        self.nber.add(rumps.separator)
        self.nber.add(rumps.MenuItem("Mark all read", callback=self.mark_all_read))

    def open_paper(self, number, _sender) -> None:
        p = next((x for x in self.papers if x["number"] == number), None)
        if not p:
            return
        webbrowser.open(self._render_page(p).as_uri())
        p["read"] = True
        self._save_digest()
        self._rebuild_nber()
        self._set_title(None, keep_bus=True)

    def mark_all_read(self, _sender) -> None:
        for p in self.papers:
            p["read"] = True
        self._save_digest()
        self._rebuild_nber()
        self._set_title(None, keep_bus=True)

    def _save_digest(self) -> None:
        data = json.loads(DIGEST_PATH.read_text()) if DIGEST_PATH.exists() else {}
        data["papers"] = self.papers
        DIGEST_PATH.write_text(json.dumps(data, indent=2))
        self._digest_mtime = DIGEST_PATH.stat().st_mtime

    def _render_page(self, p: dict) -> Path:
        PAGES_DIR.mkdir(exist_ok=True)
        e = html.escape

        def section(h, b):
            return f"<h2>{e(h)}</h2><p>{e(b)}</p>" if b else ""

        body = (section("Overview", p.get("overview") or p.get("summary", ""))
                + section("Methods", p.get("methods", ""))
                + section("Findings", p.get("findings", "")))
        authors = p.get("authors_aff")
        if authors:
            blocks = "".join(
                f'<div class="author"><span class="nm">{e(a.get("name",""))}</span>'
                f'<span class="aff">{e(a.get("affiliation") or "Affiliation not listed")}</span></div>'
                for a in authors)
            authors_html = f'<div class="authors">{blocks}</div>'
        else:
            authors_html = f'<p class="authors">{e(p.get("authors",""))}</p>'
        doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>{e(p['title'])}</title>
<style>
 body {{ font:16px/1.6 -apple-system,system-ui,sans-serif; max-width:720px; margin:48px auto;
        padding:0 24px; color:#1d1d1f; background:#fbfbfd; }}
 .score {{ display:inline-block; background:#b3261e; color:#fff; font-weight:600;
           border-radius:6px; padding:2px 10px; font-size:14px; }}
 h1 {{ font-size:26px; line-height:1.25; margin:12px 0 6px; }}
 .authors {{ margin:4px 0 0; }} .author {{ margin:0 0 8px; }}
 .nm {{ font-weight:600; display:block; }} .aff {{ color:#6e6e73; font-size:13px; display:block; }}
 h2 {{ font-size:15px; text-transform:uppercase; letter-spacing:.04em; color:#6e6e73; margin:28px 0 6px; }}
 p {{ margin:0; }}
 a.btn {{ display:inline-block; margin-top:32px; background:#0071e3; color:#fff;
          text-decoration:none; padding:10px 18px; border-radius:8px; font-weight:600; }}
</style></head><body>
<span class="score">relevance {p['score']}</span>
<h1>{e(p['title'])}</h1>
{authors_html}{body}
<a class="btn" href="{e(p.get('link',''))}">Open paper on NBER ↗</a>
</body></html>"""
        out = PAGES_DIR / f"{p['number']}.html"
        out.write_text(doc)
        return out

    # ---------- menu-bar title ----------
    def _set_title(self, next_bus, keep_bus: bool = False) -> None:
        if next_bus is not None:
            self._last_bus = next_bus
        bus = getattr(self, "_last_bus", "") if keep_bus else (next_bus or getattr(self, "_last_bus", ""))
        unread = sum(1 for p in self.papers if not p.get("read"))
        self.title = bus or "•"
        try:
            button = self._nsapp.nsstatusitem.button()
        except Exception:
            button = None
        if button is None:
            return
        if unread:
            attrs = {NSForegroundColorAttributeName: NSColor.systemRedColor()}
            button.setAttributedTitle_(
                NSAttributedString.alloc().initWithString_attributes_(self.title, attrs))
            button.setImage_(self._hazard())
            button.setImagePosition_(NSImageLeft)
        else:
            button.setAttributedTitle_(NSAttributedString.alloc().initWithString_(self.title))
            button.setImage_(symbol_image("bus.fill", "gray", 15))
            button.setImagePosition_(NSImageLeft)

    def _hazard(self):
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "exclamationmark.triangle.fill", "unread NBER")
        if img is not None:
            try:
                cfg = NSImageSymbolConfiguration.configurationWithPaletteColors_(
                    [NSColor.systemRedColor()])
                img = img.imageWithSymbolConfiguration_(cfg)
            except Exception:
                pass
            img.setTemplate_(False)
        return img


if __name__ == "__main__":
    try:
        logging.info("dashboard starting")
        Dashboard().run()
    except Exception:
        logging.error("crashed:\n%s", traceback.format_exc())
        raise
