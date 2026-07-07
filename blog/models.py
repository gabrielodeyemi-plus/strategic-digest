"""Blog domain models."""

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import List, Optional


@dataclass
class BlogPost:
    title: str
    subtitle: str
    slug: str
    date: date
    author: str
    body_markdown: str
    excerpt: str
    tags: List[str]
    seo_meta_description: str
    source_digest_date: date
    source_digest_id: str
    canonical_url: str
    status: str = "draft"
    source_ids: List[str] = field(default_factory=list)
    sources: List[dict] = field(default_factory=list)
    minimum_sources_required: int = 1

    def to_markdown(self) -> str:
        """Render portable YAML frontmatter and the article body.

        The `sources` key is emitted as a proper YAML block sequence (rather
        than an inline JSON list) so the frontmatter reads the way an editor
        would expect, e.g.:

            sources:
              - title: "..."
                url: "..."
                publisher: "..."
                date: "..."
        """
        values = {
            "title": self.title,
            "subtitle": self.subtitle,
            "date": self.date.isoformat(),
            "author": self.author,
            "slug": self.slug,
            "tags": self.tags,
            "excerpt": self.excerpt,
            "seo_description": self.seo_meta_description,
            "source": "Strategic Digest",
            "source_digest_date": self.source_digest_date.isoformat(),
            "source_digest_id": self.source_digest_id,
            "canonical_url": self.canonical_url,
            "minimum_sources_required": self.minimum_sources_required,
        }
        lines = [
            f"{key}: {json.dumps(value, ensure_ascii=False)}"
            for key, value in values.items()
        ]
        lines.append(self._sources_frontmatter_block())
        lines.append(f"status: {json.dumps(self.status, ensure_ascii=False)}")
        frontmatter = "\n".join(lines)
        return f"---\n{frontmatter}\n---\n\n{self.body_markdown.strip()}\n"

    def _sources_frontmatter_block(self) -> str:
        if not self.sources:
            return "sources: []"
        lines = ["sources:"]
        for source in self.sources:
            lines.append(
                f'  - title: {json.dumps(source.get("title", ""), ensure_ascii=False)}'
            )
            lines.append(
                f'    url: {json.dumps(source.get("url", ""), ensure_ascii=False)}'
            )
            if source.get("publisher"):
                lines.append(
                    "    publisher: "
                    + json.dumps(source["publisher"], ensure_ascii=False)
                )
            if source.get("date"):
                lines.append(
                    "    date: " + json.dumps(source["date"], ensure_ascii=False)
                )
        return "\n".join(lines)


@dataclass(frozen=True)
class QualityReport:
    passed: bool
    issues: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class PublishResult:
    status: str
    canonical_url: str
    artifact_path: Optional[Path]
    skipped: bool = False
    publisher: str = "local"
    message: str = ""

    def as_metadata(self) -> dict:
        data = asdict(self)
        data["artifact_path"] = str(self.artifact_path) if self.artifact_path else ""
        return data
