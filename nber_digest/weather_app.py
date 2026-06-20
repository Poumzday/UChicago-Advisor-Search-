#!/usr/bin/env python3
"""Menu-bar weather tab.

Shows the current condition icon + temperature (°F) in the menu bar. Clicking it
drops down today's high/low, your location, and the next 10 hours in 2-hour steps
— each with a condition icon (moon instead of sun after sunset), temperature, and
the chance of rain when it exceeds 25%. Location is auto-detected by IP; data
comes from the free Open-Meteo API (no key). Refreshes hourly.
"""

import json
import logging
import sys
import traceback
import urllib.request
from datetime import datetime
from pathlib import Path

import rumps
from AppKit import NSColor, NSImage, NSImageLeft, NSImageSymbolConfiguration

HERE = Path(__file__).resolve().parent
REFRESH_SECONDS = 3600  # update hourly

logging.basicConfig(
    filename=str(HERE / "weather.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# WMO weather code -> (daytime SF Symbol, short label, color)
WMO = {
    0: ("sun.max.fill", "Clear", "yellow"),
    1: ("sun.max.fill", "Mostly clear", "yellow"),
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
          "blue": NSColor.systemBlueColor, "indigo": NSColor.systemIndigoColor}
RAIN_THRESHOLD = 25  # only show rain chance when above this (%)


def is_night(iso: str, daily: dict) -> bool:
    """True if the local time `iso` falls outside that day's sunrise..sunset."""
    date = iso[:10]
    try:
        i = daily["time"].index(date)
    except (ValueError, KeyError):
        return False
    sr, ss = daily["sunrise"][i], daily["sunset"][i]
    return not (sr <= iso <= ss)


def condition(code: int, night: bool):
    """(SF Symbol, label, color) for a weather code, swapping sun->moon at night."""
    sym, label, color = WMO.get(code, ("cloud.fill", "—", "gray"))
    if night:
        if code in (0, 1):       # clear -> moon
            sym, color = "moon.stars.fill", "indigo"
        elif code == 2:          # partly cloudy -> cloud + moon
            sym, color = "cloud.moon.fill", "gray"
    return sym, label, color


def symbol_image(name: str, color: str, size: int = 16):
    img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
    if img is None:
        return None
    try:
        ns_color = COLORS.get(color, NSColor.systemGrayColor)()
        cfg = NSImageSymbolConfiguration.configurationWithPaletteColors_([ns_color])
        img = img.imageWithSymbolConfiguration_(cfg)
    except Exception:
        pass
    img.setTemplate_(False)
    img.setSize_((size, size))
    return img


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
        "&daily=temperature_2m_max,temperature_2m_min,sunrise,sunset"
        "&hourly=temperature_2m,weather_code,precipitation_probability"
        "&temperature_unit=fahrenheit&timezone=auto&forecast_days=2"
    )
    with urllib.request.urlopen(url, timeout=10) as r:
        wx = json.load(r)
    return {"city": city, **wx}


def hourly_rows(wx: dict) -> list[tuple]:
    """Next 10 hours, 2-hour steps -> (text, SF Symbol, color) with day/night icon."""
    h = wx["hourly"]
    times, temps, codes = h["time"], h["temperature_2m"], h["weather_code"]
    probs = h.get("precipitation_probability") or [None] * len(times)
    now = wx["current"]["time"]
    start = next((i for i, t in enumerate(times) if t >= now), 0)

    rows = []
    for offset in range(0, 10, 2):
        i = start + offset
        if i >= len(times):
            break
        iso = times[i]
        sym, label, color = condition(codes[i], is_night(iso, wx["daily"]))
        text = f"{datetime.fromisoformat(iso).strftime('%-I %p')}   ·   {round(temps[i])}°F   ·   {label}"
        p = probs[i]
        if p is not None:
            pct = round(p / 5) * 5
            if pct > RAIN_THRESHOLD:
                text += f"   ·   {pct}% rain"
        rows.append((text, sym, color))
    return rows


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
        night = is_night(cur["time"], wx["daily"])
        symbol, label, color = condition(cur["weather_code"], night)
        hi = round(wx["daily"]["temperature_2m_max"][0])
        lo = round(wx["daily"]["temperature_2m_min"][0])

        self.title = f"{temp}°F"
        self._set_button_symbol(symbol, color)

        self.menu.clear()
        items = [
            f"{label} · now {temp}°F",
            f"High {hi}°F    Low {lo}°F",
            wx["city"],
            None,
            "Next 10 hours",
        ]
        for text, sym, col in hourly_rows(wx):
            mi = rumps.MenuItem(text)
            img = symbol_image(sym, col)
            if img is not None:
                mi._menuitem.setImage_(img)
            items.append(mi)
        items += [None, rumps.MenuItem("Refresh", callback=self.refresh)]
        self.menu = items
        logging.info("rendered title=%r rows=%d", self.title, len(items))

    def _set_button_symbol(self, name: str, color: str) -> None:
        try:
            button = self._nsapp.nsstatusitem.button()
        except Exception:
            return
        if button is None:
            return
        img = symbol_image(name, color, size=16)
        if img is not None:
            button.setImage_(img)
            button.setImagePosition_(NSImageLeft)


if __name__ == "__main__":
    try:
        logging.info("starting; python=%s", sys.executable)
        WeatherMenuBar().run()
    except Exception:
        logging.error("crashed:\n%s", traceback.format_exc())
        raise
