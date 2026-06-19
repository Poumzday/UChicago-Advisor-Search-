#!/usr/bin/env python3
"""Menu-bar weather tab.

Shows the current condition icon + temperature (°F) in the menu bar. Clicking it
drops down today's high/low, your location, and an hourly line graph of the
temperature with condition labels. Location is auto-detected by IP; data comes
from the free Open-Meteo forecast API (no key). The chart is rendered by a
separate subprocess (render_chart.py) so this GUI process imports no matplotlib.
"""

import json
import logging
import subprocess
import sys
import traceback
import urllib.request
from pathlib import Path

import rumps
from AppKit import NSColor, NSImage, NSImageLeft, NSImageSymbolConfiguration

HERE = Path(__file__).resolve().parent
CHART_PATH = HERE / "pages" / "weather_today.png"
DATA_PATH = HERE / "pages" / "weather_data.json"
RENDER = HERE / "render_chart.py"
PYTHON = HERE / ".venv" / "bin" / "python"
REFRESH_SECONDS = 1800  # 30 min

logging.basicConfig(
    filename=str(HERE / "weather.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# WMO weather code -> (SF Symbol, short label, symbol color)
WMO = {
    0: ("sun.max.fill", "Clear", "yellow"),
    1: ("cloud.sun.fill", "Mostly clear", "yellow"),
    2: ("cloud.sun.fill", "Partly cloudy", "gray"),
    3: ("cloud.fill", "Cloudy", "gray"),
    45: ("cloud.fog.fill", "Fog", "gray"), 48: ("cloud.fog.fill", "Fog", "gray"),
    51: ("cloud.drizzle.fill", "Drizzle", "blue"),
    53: ("cloud.drizzle.fill", "Drizzle", "blue"),
    55: ("cloud.drizzle.fill", "Drizzle", "blue"),
    56: ("cloud.sleet.fill", "Freezing drizzle", "blue"),
    57: ("cloud.sleet.fill", "Freezing drizzle", "blue"),
    61: ("cloud.rain.fill", "Light rain", "blue"),
    63: ("cloud.rain.fill", "Rain", "blue"),
    65: ("cloud.heavyrain.fill", "Heavy rain", "blue"),
    66: ("cloud.sleet.fill", "Freezing rain", "blue"),
    67: ("cloud.sleet.fill", "Freezing rain", "blue"),
    71: ("cloud.snow.fill", "Light snow", "gray"),
    73: ("cloud.snow.fill", "Snow", "gray"),
    75: ("cloud.snow.fill", "Heavy snow", "gray"),
    77: ("cloud.snow.fill", "Snow grains", "gray"),
    80: ("cloud.rain.fill", "Showers", "blue"),
    81: ("cloud.heavyrain.fill", "Showers", "blue"),
    82: ("cloud.heavyrain.fill", "Violent showers", "blue"),
    85: ("cloud.snow.fill", "Snow showers", "gray"),
    86: ("cloud.snow.fill", "Snow showers", "gray"),
    95: ("cloud.bolt.rain.fill", "Thunderstorm", "blue"),
    96: ("cloud.bolt.rain.fill", "Thunderstorm", "blue"),
    99: ("cloud.bolt.rain.fill", "Thunderstorm", "blue"),
}
COLORS = {"yellow": NSColor.systemYellowColor, "gray": NSColor.systemGrayColor,
          "blue": NSColor.systemBlueColor}


def wmo(code: int):
    return WMO.get(code, ("cloud.fill", "—", "gray"))


def fetch_weather() -> dict:
    """Return location + current + daily + hourly forecast (°F)."""
    with urllib.request.urlopen("https://ipapi.co/json/", timeout=10) as r:
        loc = json.load(r)
    lat, lon = loc["latitude"], loc["longitude"]
    city = loc.get("city", "your area")
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,weather_code"
        "&daily=temperature_2m_max,temperature_2m_min"
        "&hourly=temperature_2m,weather_code"
        "&temperature_unit=fahrenheit&timezone=auto&forecast_days=1"
    )
    with urllib.request.urlopen(url, timeout=10) as r:
        wx = json.load(r)
    return {"city": city, **wx}


class WeatherMenuBar(rumps.App):
    def __init__(self) -> None:
        super().__init__("…", quit_button="Quit")
        rumps.Timer(self.refresh, REFRESH_SECONDS).start()
        self._startup = rumps.Timer(self._on_startup, 1)
        self._startup.start()

    def _on_startup(self, timer) -> None:
        timer.stop()
        self.refresh(None)

    def refresh(self, _sender) -> None:
        try:
            self._render(fetch_weather())
        except Exception:
            logging.error("refresh failed:\n%s", traceback.format_exc())
            self.title = "wx?"
            self.menu.clear()
            self.menu = ["Weather unavailable",
                         rumps.MenuItem("Retry", callback=self.refresh)]

    def _render(self, wx: dict) -> None:
        cur = wx["current"]
        temp = round(cur["temperature_2m"])
        symbol, label, color = wmo(cur["weather_code"])
        hi = round(wx["daily"]["temperature_2m_max"][0])
        lo = round(wx["daily"]["temperature_2m_min"][0])
        self._make_chart(wx)

        self.title = f"{temp}°F"
        self._set_symbol(symbol, color)

        self.menu.clear()
        items = [
            f"{label} · now {temp}°F",
            f"High {hi}°F    Low {lo}°F",
            wx["city"],
            None,
        ]
        if CHART_PATH.exists():
            chart_item = rumps.MenuItem("")
            chart_item.set_icon(str(CHART_PATH), dimensions=(340, 170))
            items.append(chart_item)
            items.append(None)
        items.append(rumps.MenuItem("Refresh", callback=self.refresh))
        self.menu = items

    def _make_chart(self, wx: dict) -> None:
        """Render the hourly chart in a subprocess (keeps matplotlib out of here)."""
        data = {
            "times": wx["hourly"]["time"],
            "temps": wx["hourly"]["temperature_2m"],
            "labels": [wmo(c)[1] for c in wx["hourly"]["weather_code"]],
            "title": "Today's temperature",
        }
        DATA_PATH.parent.mkdir(exist_ok=True)
        DATA_PATH.write_text(json.dumps(data))
        try:
            subprocess.run([str(PYTHON), str(RENDER), str(DATA_PATH), str(CHART_PATH)],
                           check=True, capture_output=True, timeout=60)
        except Exception:
            logging.error("chart render failed:\n%s", traceback.format_exc())

    def _set_symbol(self, name: str, color: str) -> None:
        try:
            button = self._nsapp.nsstatusitem.button()
        except Exception:
            return
        if button is None:
            return
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
        if img is not None:
            try:
                ns_color = COLORS.get(color, NSColor.systemGrayColor)()
                cfg = NSImageSymbolConfiguration.configurationWithPaletteColors_([ns_color])
                img = img.imageWithSymbolConfiguration_(cfg)
            except Exception:
                pass
            img.setTemplate_(False)
            button.setImage_(img)
            button.setImagePosition_(NSImageLeft)


if __name__ == "__main__":
    try:
        logging.info("starting; python=%s", sys.executable)
        WeatherMenuBar().run()
    except Exception:
        logging.error("crashed:\n%s", traceback.format_exc())
        raise
