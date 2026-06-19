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
import sys
from pathlib import Path

import anthropic
import feedparser

HERE = Path(__file__).resolve().parent
NBER_FEED = "https://back.nber.org/rss/new.xml"
PROFILE_PATH = HERE / "profile.md"
SEEN_PATH = HERE / "seen_papers.json"
DIGEST_PATH = HERE / "digest.json"
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
                    "authors": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "affiliation": {"type": "string"},
                            },
                            "required": ["name", "affiliation"],
                            "additionalProperties": False,
                        },
                    },
                    "overview": {"type": "string"},
                    "methods": {"type": "string"},
                    "findings": {"type": "string"},
                },
                "required": ["number", "score", "authors", "overview", "methods", "findings"],
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
        "match. For each paper return: an integer `score` 0-100; `authors`, a list "
        "of {name, affiliation} for every author (give each author's current "
        "institutional affiliation from your knowledge, e.g. 'University of Chicago, "
        "Booth School of Business'; use 'Affiliation not listed' only if you truly "
        "don't know); and a one-page write-up as three plain-prose fields: "
        "`overview` (2-4 sentences on the question and what the paper does), "
        "`methods` (a detailed paragraph of 5-8 sentences covering the data and "
        "sample, identification strategy, estimation technique, key specifications, "
        "and any robustness or validation), and `findings` (3-4 sentences on the "
        "main results and their magnitudes).\n\n"
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


def write_digest(top: list[dict], by_number: dict[str, dict]) -> None:
    """Write the scored top papers to digest.json for the menu-bar app.

    Read state is preserved for papers that were already in the previous digest,
    so re-running mid-week doesn't mark already-read papers unread again.
    """
    prev_read: dict[str, bool] = {}
    if DIGEST_PATH.exists():
        for p in json.loads(DIGEST_PATH.read_text()).get("papers", []):
            prev_read[p["number"]] = p.get("read", False)

    papers = []
    for s in top:
        paper = by_number.get(s["number"], {})
        papers.append(
            {
                "number": s["number"],
                "title": paper.get("title", s["number"]),
                "authors": paper.get("authors", ""),
                "link": paper.get("link", ""),
                "score": s["score"],
                "authors_aff": s["authors"],
                "overview": s["overview"],
                "methods": s["methods"],
                "findings": s["findings"],
                "read": prev_read.get(s["number"], False),
            }
        )
    DIGEST_PATH.write_text(
        json.dumps({"threshold": SCORE_THRESHOLD, "papers": papers}, indent=2)
    )


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

    write_digest(top, by_number)
    if top:
        print(f"{len(top)} new paper(s) above {SCORE_THRESHOLD}; wrote {DIGEST_PATH.name}.")
        for s in top:
            print(f"  [{s['score']}] {by_number[s['number']]['title']}")
    else:
        print(f"No new NBER papers scored above {SCORE_THRESHOLD} this week.")

    # Only mark as seen after a successful run, so failures retry next time.
    save_seen(seen | {p["number"] for p in papers})
    return 0


if __name__ == "__main__":
    sys.exit(main())
