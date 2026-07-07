"""Deterministic and model-assisted editorial quality gates."""

import json
import os
import re
from typing import List, Optional

import anthropic

from blog.config import BlogConfig
from blog.models import BlogPost, QualityReport
from blog.sources import extract_links, has_visible_sources, split_article_and_sources
from digest_models import Digest


_BANNED_PHRASES = (
    "in today's fast-paced world",
    "it's important to note",
    "this underscores",
    "delve",
    "landscape",
    "game-changer",
    "navigating",
    "robust",
)

_REVIEW_SYSTEM = """You are a strict fact-checker. Compare the proposed article
only with the supplied daily digest and source cards. Flag a factual claim if the
packet does not support it. Do not flag clearly labeled strategic interpretation
or cautious inference. Flag invented quotations, statistics, source attributions,
and URLs. Return valid JSON only with keys: passed (boolean), issues (array of
specific strings). Do not use a Markdown code fence."""


class BlogQualityGate:
    def __init__(
        self,
        config: BlogConfig,
        client=None,
        model: Optional[str] = None,
    ):
        self.config = config
        self.client = client
        self.model = model or os.environ.get(
            "BLOG_CLAUDE_MODEL",
            os.environ.get("CLAUDE_MODEL", "claude-opus-4-8"),
        )

    def evaluate(self, post: BlogPost, digest: Digest) -> QualityReport:
        issues = self._deterministic_issues(post, digest)
        if issues or not self.config.quality_review_enabled:
            return QualityReport(passed=not issues, issues=issues)

        review = self._grounding_review(post, digest)
        return QualityReport(
            passed=bool(review.get("passed")) and not review.get("issues"),
            issues=[str(issue) for issue in review.get("issues", [])],
        )

    def _deterministic_issues(
        self, post: BlogPost, digest: Digest
    ) -> List[str]:
        issues = []
        article_body, sources_section = split_article_and_sources(
            post.body_markdown
        )

        word_count = len(re.findall(r"\b[\w’'-]+\b", article_body))
        if word_count < self.config.minimum_words:
            issues.append(
                f"Article is {word_count} words; minimum is "
                f"{self.config.minimum_words}."
            )
        if word_count > self.config.maximum_words:
            issues.append(
                f"Article is {word_count} words; maximum is "
                f"{self.config.maximum_words}."
            )
        if len(post.title.split()) < 5:
            issues.append("Headline is not specific enough.")
        if "—" in " ".join(
            [post.title, post.subtitle, post.excerpt, article_body]
        ):
            issues.append("Article contains an em dash.")

        combined = " ".join(
            [post.title, post.subtitle, post.excerpt, article_body]
        ).lower()
        found = [phrase for phrase in _BANNED_PHRASES if phrase in combined]
        if found:
            issues.append("Article contains banned phrasing: " + ", ".join(found))

        headings = re.findall(r"^##\s+(.+?)\s*$", article_body, re.MULTILINE)
        if not 3 <= len(headings) <= 5:
            issues.append("Article must contain 3 to 5 H2 sections.")
        if not headings or headings[-1] != "The Strategic Read":
            issues.append('Final H2 section must be "The Strategic Read".')

        opening = article_body.split("##", 1)[0].strip()
        if len(opening.split()) < 40:
            issues.append("Opening thesis paragraph is too thin.")
        if opening.startswith(("-", "*", "1.")):
            issues.append("Article opens like a list instead of a narrative.")

        allowed_ids = {card["id"] for card in digest.source_cards()}
        unknown_ids = set(post.source_ids) - allowed_ids
        if unknown_ids:
            issues.append(
                "Article cites unknown source IDs: " + ", ".join(sorted(unknown_ids))
            )

        allowed_urls = {
            card["url"] for card in digest.source_cards() if card.get("url")
        }
        article_urls = set(extract_links(post.body_markdown))
        unknown_urls = article_urls - allowed_urls
        if unknown_urls:
            issues.append(
                "Article includes URLs absent from the source packet: "
                + ", ".join(sorted(unknown_urls))
            )

        if post.body_markdown.count("[") != post.body_markdown.count("]"):
            issues.append("Article appears to contain broken Markdown links.")
        if len(post.seo_meta_description) > 160:
            issues.append("SEO meta description exceeds 160 characters.")
        if not 3 <= len(post.tags) <= 6:
            issues.append("Article must have 3 to 6 tags.")

        issues.extend(self._source_grounding_issues(post, digest, sources_section))
        return issues

    def _source_grounding_issues(
        self, post: BlogPost, digest: Digest, sources_section
    ) -> List[str]:
        issues = []
        if not digest.source_cards():
            issues.append(
                "sources_missing: this digest carries no source metadata, so "
                "no article generated from it can be publicly published."
            )
            return issues

        if not has_visible_sources(sources_section):
            issues.append(
                'Article is missing a visible "## Sources" section with at '
                "least one linked source."
            )

        valid_sources = [
            source for source in post.sources if source.get("url")
        ]
        if not valid_sources:
            issues.append("Article has no valid source URLs to cite.")

        required = post.minimum_sources_required
        if required and len(valid_sources) < required:
            issues.append(
                "Source coverage below threshold: "
                f"{len(valid_sources)} valid sources found, {required} expected."
            )
        return issues

    def _grounding_review(self, post: BlogPost, digest: Digest) -> dict:
        client = self.client or anthropic.Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"]
        )
        response = client.messages.create(
            model=self.model,
            max_tokens=1800,
            system=_REVIEW_SYSTEM,
            messages=[{
                "role": "user",
                "content": json.dumps({
                    "digest": digest.briefing,
                    "source_cards": digest.source_cards(),
                    "article": {
                        "title": post.title,
                        "subtitle": post.subtitle,
                        "body_markdown": post.body_markdown,
                    },
                }, ensure_ascii=False),
            }],
        )
        text = "".join(
            getattr(block, "text", "")
            for block in response.content
            if getattr(block, "type", "text") == "text"
        ).strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        return json.loads(fenced.group(1) if fenced else text)
