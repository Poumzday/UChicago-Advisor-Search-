#!/usr/bin/env python3
"""Weekly NBER working-paper digest, scored against Poum's interest profile.

Fetches the latest NBER working papers, scores each one for relevance using the
Claude API (topic-dominant, with a Chicago > general-fame author tiebreaker),
and pops up a desktop dialog summarizing the papers that score above a threshold.

Run manually:   python3 nber_digest.py
Scheduled:      via launchd (see install.sh)
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import anthropic
import feedparser

HERE = Path(__file__).resolve().parent
NBER_FEED = "https://back.nber.org/rss/new.xml"
PROFILE_PATH = HERE / "profile.md"
SEEN_PATH = HERE / "seen_papers.json"
SCORE_THRESHOLD = 80
MODEL = os.environ.get("NBER_MODEL", "claude-opus-4-8")


def load_env() -> None:
    """Load KEY=value lines from a sibling .env (launchd has no shell env)."""
    env_file = HERE / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def fetch_papers() -> list[dict]:
    """Return the current NBER new-working-papers batch."""
    feed = feedparser.parse(NBER_FEED)
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"Could not parse NBER feed: {feed.bozo_exception}")
    papers = []
    for entry in feed.entries:
        link = entry.get("link", "").split("#")[0]  # drop #fromrss fragment
        number = link.rstrip("/").split("/")[-1]  # e.g. w35315
        # NBER puts the byline in the title: "Title -- by Author, Author"
        raw_title = entry.get("title", "").strip()
        title, _, byline = raw_title.partition(" -- by ")
        authors = entry.get("author", "").strip() or byline.strip()
        papers.append(
            {
                "number": number,
                "title": title.strip(),
                "authors": authors,
                "abstract": entry.get("summary", "").strip(),
                "link": link,
            }
        )
    if not papers:
        raise RuntimeError("NBER feed returned no papers.")
    return papers


def load_seen() -> set[str]:
    if SEEN_PATH.exists():
        return set(json.loads(SEEN_PATH.read_text()))
    return set()


def save_seen(seen: set[str]) -> None:
    SEEN_PATH.write_text(json.dumps(sorted(seen)))


SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "papers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "string"},
                    "score": {"type": "integer"},
                    "summary": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["number", "score", "summary", "why"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["papers"],
    "additionalProperties": False,
}


def score_papers(papers: list[dict], profile: str) -> dict[str, dict]:
    """Score each paper 0-100 and write a 5-line summary. Keyed by NBER number."""
    client = anthropic.Anthropic()
    system = (
        "You score new NBER working papers for relevance to one economist, using "
        "their interest profile. Follow the profile's scoring rubric exactly: "
        "topic/area fit is dominant and sets the tier; author reputation only "
        "breaks ties and nudges across tiers (Chicago/Booth economists get a larger "
        "bump than generally-famous economists) and never overrides a weak topic "
        "match. For each paper return an integer score 0-100, a `summary` of exactly "
        "five short lines separated by newlines (plain prose, no bullets), and a "
        "one-sentence `why` explaining the relevance and any author bump applied.\n\n"
        f"=== INTEREST PROFILE ===\n{profile}"
    )
    payload = [
        {
            "number": p["number"],
            "title": p["title"],
            "authors": p["authors"],
            "abstract": p["abstract"],
        }
        for p in papers
    ]
    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCORE_SCHEMA}},
        system=system,
        messages=[
            {
                "role": "user",
                "content": "Score every paper in this list:\n\n"
                + json.dumps(payload, indent=2),
            }
        ],
    )
    text = next(b.text for b in response.content if b.type == "text")
    scored = json.loads(text)["papers"]
    return {item["number"]: item for item in scored}


def notify(title: str, message: str) -> None:
    """Show a desktop dialog that stays until dismissed (passes text via argv)."""
    script = (
        'on run argv\n'
        '  display dialog (item 1 of argv) with title (item 2 of argv) '
        'buttons {"OK"} default button "OK" with icon note\n'
        'end run'
    )
    subprocess.run(["osascript", "-e", script, message, title], check=False)


def main() -> int:
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set (put it in nber_digest/.env).", file=sys.stderr)
        return 1

    profile = PROFILE_PATH.read_text()
    papers = fetch_papers()
    seen = load_seen()
    new_papers = [p for p in papers if p["number"] not in seen]

    if not new_papers:
        print("No new NBER papers since last run.")
        return 0

    scores = score_papers(new_papers, profile)
    by_number = {p["number"]: p for p in new_papers}

    top = sorted(
        (s for s in scores.values() if s["score"] > SCORE_THRESHOLD),
        key=lambda s: s["score"],
        reverse=True,
    )

    if top:
        blocks = []
        for s in top:
            paper = by_number.get(s["number"], {})
            blocks.append(
                f"[{s['score']}] {paper.get('title', s['number'])}\n"
                f"{paper.get('authors', '')}\n"
                f"{s['summary']}\n"
                f"{paper.get('link', '')}"
            )
        message = f"{len(top)} new NBER paper(s) above {SCORE_THRESHOLD}:\n\n" + "\n\n———\n\n".join(blocks)
        notify("NBER digest — top papers for you", message)
        print(message)
    else:
        print(f"No new NBER papers scored above {SCORE_THRESHOLD} this week.")

    # Only mark as seen after a successful run, so failures retry next time.
    save_seen(seen | {p["number"] for p in papers})
    return 0


if __name__ == "__main__":
    sys.exit(main())
