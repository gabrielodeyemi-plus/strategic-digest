#!/usr/bin/env python3
"""
Strategic Intelligence Digest — daily orchestrator.

Run manually:  python main.py
Run via cron:  installed by install.sh as a 7am launchd job
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import emailer
import fetcher
import notion_pusher
import synthesizer


def main():
    print("── Strategic Intelligence Digest ─────────────────────")

    # 1. Load topics
    topics_path = Path(__file__).parent / "topics.yaml"
    print(f"Loading topics from {topics_path.name}...")
    topics = fetcher.load_topics(str(topics_path))
    print(f"  {len(topics)} topics configured")

    # 2. Fetch articles
    print("Fetching articles...")
    articles_by_topic = fetcher.fetch_all(topics)
    total = sum(len(v) for v in articles_by_topic.values())
    print(f"  {total} articles fetched")
    for topic, arts in articles_by_topic.items():
        print(f"    {topic}: {len(arts)} articles")

    if total == 0:
        print("No articles found. Check your RSS feeds.")
        sys.exit(0)

    # 3. Synthesize with Claude
    print("Synthesizing with Claude...")
    briefing = synthesizer.synthesize(articles_by_topic)
    print(f"  Briefing generated ({len(briefing.split())} words)")

    # 4. Push to Notion
    notion_url = ""
    try:
        print("Pushing to Notion...")
        notion_url = notion_pusher.push(briefing)
        print(f"  {notion_url}")
    except Exception as e:
        print(f"  Notion push failed: {e}")

    # 5. Send email
    try:
        print("Sending email...")
        emailer.send(briefing, notion_url)
    except Exception as e:
        print(f"  Email failed: {e}")
        print("  Tip: check GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env")

    print("── Done ───────────────────────────────────────────────")


if __name__ == "__main__":
    main()
