"""
Fetches articles from RSS feeds defined in topics.yaml.
Returns a dict of {topic_name: [article, ...]} with at most MAX_PER_FEED
articles per feed, filtered to the last 48 hours.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import feedparser
import yaml

MAX_PER_FEED = 4
MAX_SUMMARY_CHARS = 600
FETCH_TIMEOUT = 10


def load_topics(path: str = "topics.yaml") -> list[dict]:
    with open(path) as f:
        return yaml.safe_load(f)["topics"]


def fetch_all(topics: List[dict]) -> Dict[str, List[dict]]:
    """Returns {topic_name: [article_dict, ...]}."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    results: dict[str, list] = {}

    for topic in topics:
        articles: list[dict] = []
        for feed_cfg in topic.get("feeds", []):
            url = feed_cfg.get("url", "")
            label = feed_cfg.get("label", url)
            try:
                entries = _fetch_feed(url, label, cutoff)
                articles.extend(entries)
            except Exception as e:
                print(f"  [skip] {label}: {e}")

        # Sort newest first, keep top articles per topic
        articles.sort(key=lambda a: a["published"], reverse=True)
        results[topic["name"]] = articles[:MAX_PER_FEED * len(topic.get("feeds", [1]))]

    return results


def _fetch_feed(url: str, label: str, cutoff: datetime) -> List[dict]:
    feed = feedparser.parse(url, agent="StrategicDigest/1.0", request_headers={"Accept": "application/rss+xml"})

    articles = []
    for entry in feed.entries[:MAX_PER_FEED * 2]:
        pub = _parse_date(entry)
        if pub and pub < cutoff:
            continue

        summary = (
            entry.get("summary")
            or entry.get("description")
            or entry.get("content", [{}])[0].get("value", "")
        )
        # Strip HTML tags
        import re
        summary = re.sub(r"<[^>]+>", " ", summary).strip()
        summary = re.sub(r"\s+", " ", summary)[:MAX_SUMMARY_CHARS]

        articles.append({
            "source": label,
            "title": entry.get("title", "").strip(),
            "summary": summary,
            "url": entry.get("link", ""),
            "published": pub or datetime.now(timezone.utc),
        })

    return articles[:MAX_PER_FEED]


def _parse_date(entry) -> Optional[datetime]:
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        t = entry.get(field)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None
