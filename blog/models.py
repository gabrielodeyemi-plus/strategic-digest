"""Blog domain models."""

from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import List, Optional

from blog.frontmatter import serialize_frontmatter


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
        frontmatter = {
            "title": self.title,
            "subtitle": self.subtitle,
            "date": self.date.isoformat(),
            "author": self.author,
            "slug": self.slug,
            "tags": self.tags,
            "excerpt": self.excerpt,
            "seo_description": self.seo_meta_description,
            "seo_title": self.seo_title,
            "topic_cluster": self.topic_cluster,
            "primary_keyword": self.primary_keyword,
            "secondary_keywords": self.secondary_keywords,
            "source": "Strategic Digest",
            "source_digest_date": self.source_digest_date.isoformat(),
            "source_digest_id": self.source_digest_id,
            "canonical_url": self.canonical_url,
            "status": self.status,
            "minimum_sources_required": self.minimum_sources_required,
            "internal_link_targets": self.internal_link_targets,
            "suggested_related_posts": self.suggested_related_posts,
            "sources": self.sources,
        }
        return f"---\n{serialize_frontmatter(frontmatter)}\n---\n\n{self.body_markdown.strip()}\n"


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
