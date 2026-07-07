"""Transform a compact daily digest into a standalone strategic article."""

import json
import os
import re
from typing import List, Optional

import anthropic

from blog.config import BlogConfig
from blog.models import BlogPost
from blog.sources import (
    format_sources_section,
    is_valid_url,
    short_date,
    strip_sources_section,
)
from digest_models import Digest


_SYSTEM = """You are the editor of a rigorous business and strategy publication.
Turn a daily intelligence digest into a standalone analysis article. Write with
the precision, restraint, context, and narrative control of excellent newspaper
business analysis. The result must not read like a newsletter or a list of news.

Grounding rules:
- Use only the supplied digest and source cards.
- Do not invent facts, quotes, statistics, links, names, dates, or causality.
- Preserve uncertainty and clearly label analysis as analysis.
- A source-card summary is not permission to add details from memory.
- Use only exact URLs present in the source cards.

Editorial rules:
- Open with a specific narrative lead that establishes the central thesis.
- Organize around the most consequential theme, not the order of source items.
- Put context before detail and make the strategic judgment explicit.
- Use elegant plain language, active voice, and restrained executive-level prose.
- Include 3 to 5 descriptive section headings.
- End with a section headed exactly "## The Strategic Read".
- Do not write your own "Sources" or "## Sources" section. The publishing
  system appends a verified Sources section automatically from source_ids;
  a model-written one would be discarded.
- Do not use em dashes.
- Avoid generic AI, hype, LinkedIn, and newsletter language.
- Do not use: "In today's fast-paced world", "It's important to note",
  "This underscores", "delve", "landscape", "game-changer", "navigating",
  or "robust".

Return valid JSON only. Do not use a Markdown code fence."""


_PROMPT = """Digest date: {digest_date}
Author: {author}
Required body length: {minimum_words} to {maximum_words} words.

DAILY DIGEST:
{briefing}

SOURCE CARDS:
{source_cards}

Produce a JSON object with exactly these keys:
- title: a specific, compelling headline
- subtitle: a one-sentence dek
- excerpt: 35 to 60 words
- body_markdown: opening thesis paragraph, then 3 to 5 H2 sections, with the
  final H2 exactly "The Strategic Read"; do not repeat the title, dek, byline,
  or date in the body
- tags: 3 to 6 concise strings
- seo_meta_description: at most 160 characters
- slug: lowercase URL slug
- source_ids: IDs of every source card relied upon for a factual claim; this
  list is used to build the visible, published Sources section, so it must
  include every card whose fact appears in body_markdown

The article must synthesize the evidence into analysis. It must not merely expand
the digest bullets. If the digest has no source cards, treat the digest itself as
the sole source and do not add links or external facts.
{revision_notes}"""


class BlogArticleTransformer:
    def __init__(
        self,
        config: BlogConfig,
        client=None,
        model: Optional[str] = None,
    ):
        self.config = config
        self.client = client or anthropic.Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"]
        )
        self.model = model or os.environ.get(
            "BLOG_CLAUDE_MODEL",
            os.environ.get("CLAUDE_MODEL", "claude-opus-4-8"),
        )

    def transform(
        self,
        digest: Digest,
        revision_issues: Optional[List[str]] = None,
    ) -> BlogPost:
        cards = digest.source_cards()
        notes = ""
        if revision_issues:
            notes = (
                "\nREVISION REQUIRED. Correct every issue below:\n- "
                + "\n- ".join(revision_issues)
            )
        response = self.client.messages.create(
            model=self.model,
            max_tokens=6500,
            system=_SYSTEM,
            messages=[{
                "role": "user",
                "content": _PROMPT.format(
                    digest_date=digest.digest_date.isoformat(),
                    author=self.config.author,
                    minimum_words=self.config.minimum_words,
                    maximum_words=self.config.maximum_words,
                    briefing=digest.briefing,
                    source_cards=json.dumps(cards, ensure_ascii=False, indent=2),
                    revision_notes=notes,
                ),
            }],
        )
        payload = json.loads(_response_text(response))
        slug = _slugify(payload["slug"] or payload["title"])
        canonical_url = f"{self.config.base_url}/blog/{slug}"

        source_ids = [
            str(source_id).strip()
            for source_id in payload.get("source_ids", [])
            if str(source_id).strip()
        ]
        resolved_sources = _resolve_sources(cards, source_ids)
        minimum_required = _minimum_sources_required(digest)

        body = strip_sources_section(payload["body_markdown"].strip())
        body = f"{body}\n\n{format_sources_section(resolved_sources)}"

        return BlogPost(
            title=payload["title"].strip(),
            subtitle=payload["subtitle"].strip(),
            slug=slug,
            date=digest.digest_date,
            author=self.config.author,
            body_markdown=body,
            excerpt=payload["excerpt"].strip(),
            tags=[str(tag).strip() for tag in payload["tags"] if str(tag).strip()],
            seo_meta_description=payload["seo_meta_description"].strip(),
            source_digest_date=digest.digest_date,
            source_digest_id=digest.digest_id,
            canonical_url=canonical_url,
            status=self.config.default_status,
            source_ids=source_ids,
            sources=resolved_sources,
            minimum_sources_required=minimum_required,
        )


def _resolve_sources(cards: List[dict], source_ids: List[str]) -> List[dict]:
    """Resolve cited source_ids to real, deduplicated, valid-URL source refs.

    Titles, URLs, and publishers come only from the source cards supplied by
    the digest. Nothing here is invented; cards with missing or invalid URLs
    are silently excluded from the visible list rather than being faked.
    """
    cards_by_id = {card["id"]: card for card in cards}
    seen_urls = set()
    resolved = []
    for source_id in source_ids:
        card = cards_by_id.get(source_id)
        if not card:
            continue
        url = (card.get("url") or "").strip()
        if not is_valid_url(url) or url in seen_urls:
            continue
        seen_urls.add(url)
        resolved.append({
            "title": (card.get("title") or "").strip() or "Untitled source",
            "url": url,
            "publisher": (card.get("source") or "").strip(),
            "date": short_date(card.get("published")),
        })
    return resolved


def _minimum_sources_required(digest: Digest) -> int:
    """Business rule: 0 sources available -> blocked; 1 -> single item;
    2 or more -> require 3 (capped at what the digest actually has)."""
    distinct = len(digest.distinct_source_urls())
    if distinct == 0:
        return 0
    if distinct == 1:
        return 1
    return min(3, distinct)


def _response_text(response) -> str:
    text = "".join(
        getattr(block, "text", "")
        for block in response.content
        if getattr(block, "type", "text") == "text"
    ).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    return fenced.group(1) if fenced else text


def _slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")[:96] or "strategic-digest"
