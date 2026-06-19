#!/usr/bin/env python3
"""Render today's hourly temperature chart to a PNG.

Standalone so the menu-bar process never imports matplotlib (which crashes when
imported inside a launchd GUI app). Usage: render_chart.py <data.json> <out.png>
where data.json has keys: times (ISO list), temps, labels, title.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parent / ".mplcache"))
os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt


def main(data_path: str, out_path: str) -> None:
    d = json.loads(Path(data_path).read_text())
    times = [datetime.fromisoformat(t) for t in d["times"]]
    temps = d["temps"]
    labels = d["labels"]

    fig, ax = plt.subplots(figsize=(4.4, 2.2), dpi=160)
    ax.plot(times, temps, "-o", color="#0071e3", markersize=3, linewidth=2)
    for i in range(0, len(times), 3):
        ax.annotate(labels[i], (times[i], temps[i]), textcoords="offset points",
                    xytext=(0, 8), ha="center", fontsize=6, color="#6e6e73", rotation=30)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%-I%p"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=3))
    ax.set_ylabel("Temperature (°F)", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(True, alpha=0.25)
    ax.set_title(d.get("title", "Today's temperature"), fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
