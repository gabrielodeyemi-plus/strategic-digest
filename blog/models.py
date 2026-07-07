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
    # Discoverability metadata (see blog/seo.py for the controlled vocabulary
    # and validation rules). All optional/empty by default so older callers
    # and fixtures that predate this feature keep constructing a BlogPost
    # without any changes.
    seo_title: str = ""
    topic_cluster: str = ""
    primary_keyword: str = ""
    secondary_keywords: List[str] = field(default_factory=list)
    internal_link_targets: List[dict] = field(default_factory=list)
    suggested_related_posts: List[dict] = field(default_factory=list)

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
        }
        seo_values = {
            "seo_title": self.seo_title,
            "topic_cluster": self.topic_cluster,
            "primary_keyword": self.primary_keyword,
            "secondary_keywords": self.secondary_keywords,
        }
        trailing_values = {
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
        lines.extend(
            f"{key}: {json.dumps(value, ensure_ascii=False)}"
            for key, value in seo_values.items()
        )
        lines.extend(
            f"{key}: {json.dumps(value, ensure_ascii=False)}"
            for key, value in trailing_values.items()
        )
        lines.append(self._internal_link_targets_block())
        lines.append(self._suggested_related_posts_block())
        lines.append(self._sources_frontmatter_block())
        lines.append(f"status: {json.dumps(self.status, ensure_ascii=False)}")
        frontmatter = "\n".join(lines)
        return f"---\n{frontmatter}\n---\n\n{self.body_markdown.strip()}\n"

    def _internal_link_targets_block(self) -> str:
        """Renders `internal_link_targets` as a YAML block sequence of
        {label, url, reason?, status?} objects, e.g.:

            internal_link_targets:
              - label: "Strategic Digest"
                url: "/blog"
                reason: "..."
                status: "planned"
        """
        return _link_list_block("internal_link_targets", self.internal_link_targets, "label")

    def _suggested_related_posts_block(self) -> str:
        """Renders `suggested_related_posts` as a YAML block sequence of
        {title, url, reason?} objects, mirroring `_internal_link_targets_block`
        but keyed on `title` (an existing post's headline) instead of `label`.
        """
        return _link_list_block("suggested_related_posts", self.suggested_related_posts, "title")

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


def _link_list_block(field_name: str, items: List[dict], name_key: str) -> str:
    """Shared renderer for the two link-list frontmatter fields
    (`internal_link_targets`, `suggested_related_posts`), which share the
    same {name_key, url, reason?, status?} shape. A bare string item is
    tolerated and rendered with an empty url, so a less-structured transformer
    payload degrades gracefully instead of raising.
    """
    if not items:
        return f"{field_name}: []"
    lines = [f"{field_name}:"]
    for item in items:
        entry = item if isinstance(item, dict) else {name_key: str(item)}
        lines.append(
            f'  - {name_key}: {json.dumps(entry.get(name_key, ""), ensure_ascii=False)}'
        )
        lines.append(f'    url: {json.dumps(entry.get("url", ""), ensure_ascii=False)}')
        if entry.get("reason"):
            lines.append(
                "    reason: " + json.dumps(entry["reason"], ensure_ascii=False)
            )
        if entry.get("status"):
            lines.append(
                "    status: " + json.dumps(entry["status"], ensure_ascii=False)
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
