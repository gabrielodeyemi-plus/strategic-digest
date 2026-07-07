"""Typed data exchanged between the digest and output adapters."""

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List


@dataclass(frozen=True)
class Digest:
    """The generated briefing plus the source cards used to create it."""

    digest_id: str
    digest_date: date
    briefing: str
    articles_by_topic: Dict[str, List[dict]] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        briefing: str,
        articles_by_topic: Dict[str, List[dict]],
        digest_date: date = None,
    ) -> "Digest":
        day = digest_date or date.today()
        return cls(
            digest_id=f"strategic-digest-{day.isoformat()}",
            digest_date=day,
            briefing=briefing,
            articles_by_topic=articles_by_topic,
        )

    def source_cards(self) -> List[dict]:
        """Return JSON-safe source cards with stable IDs for grounding."""
        cards = []
        sequence = 1
        for topic, articles in self.articles_by_topic.items():
            for article in articles:
                published = article.get("published", "")
                if isinstance(published, (date, datetime)):
                    published = published.isoformat()
                cards.append({
                    "id": f"S{sequence:03d}",
                    "topic": topic,
                    "source": article.get("source", ""),
                    "title": article.get("title", ""),
                    "summary": article.get("summary", ""),
                    "url": article.get("url", ""),
                    "published": str(published),
                })
                sequence += 1
        return cards

    def distinct_source_urls(self) -> List[str]:
        """Distinct, valid (http/https) source URLs available to this digest."""
        seen: List[str] = []
        for card in self.source_cards():
            url = (card.get("url") or "").strip()
            if url and url.startswith(("http://", "https://")) and url not in seen:
                seen.append(url)
        return seen

    def to_dict(self) -> dict:
        """JSON-safe representation preserving source metadata for later reuse."""
        articles_by_topic = {}
        for topic, articles in self.articles_by_topic.items():
            serialized = []
            for article in articles:
                item = dict(article)
                published = item.get("published", "")
                if isinstance(published, (date, datetime)):
                    item["published"] = published.isoformat()
                else:
                    item["published"] = str(published) if published else ""
                serialized.append(item)
            articles_by_topic[topic] = serialized
        return {
            "digest_id": self.digest_id,
            "digest_date": self.digest_date.isoformat(),
            "briefing": self.briefing,
            "articles_by_topic": articles_by_topic,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Digest":
        return cls(
            digest_id=data["digest_id"],
            digest_date=date.fromisoformat(data["digest_date"]),
            briefing=data["briefing"],
            articles_by_topic=data.get("articles_by_topic", {}) or {},
        )

    def save(self, output_dir: Path) -> Path:
        """Persist the full digest, including source metadata, as JSON.

        This is the durable record that lets the blog pipeline be re-run
        later (e.g. `blog:regenerate`) without losing source URLs once the
        originating RSS items age out of their feeds.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{self.digest_date.isoformat()}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return path

    @classmethod
    def load(cls, path: Path) -> "Digest":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
