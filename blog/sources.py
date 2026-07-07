"""Shared helpers for source citation formatting and validation.

Centralizing this logic keeps the transformer (which builds the visible
Sources section), the quality gate (which checks it), and the approval CLI
(which enforces it at publish time) working from one definition of what a
"valid, visible source" is.
"""

import re
from typing import List, Optional, Tuple

SOURCES_HEADING = "## Sources"

_URL_RE = re.compile(r"^https?://\S+$")
_HEADING_RE = re.compile(r"(?m)^##\s+Sources\s*$")
_LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^)\s]+)\)")

_UNAVAILABLE_NOTE = (
    "_No verifiable source metadata was available for this digest. "
    "This draft cannot pass source-coverage review until sources exist._"
)


def is_valid_url(url: Optional[str]) -> bool:
    """A conservative check: http(s) scheme, no embedded whitespace."""
    return bool(url) and bool(_URL_RE.match(url.strip()))


def short_date(value: Optional[str]) -> str:
    """Best-effort extraction of a YYYY-MM-DD date from a source card value."""
    if not value:
        return ""
    text = str(value).strip()
    match = re.match(r"^\d{4}-\d{2}-\d{2}", text)
    return match.group(0) if match else text


def format_sources_section(sources: List[dict]) -> str:
    """Render the canonical, deterministic '## Sources' body section.

    Titles and URLs must come from source metadata, never be invented here.
    """
    if not sources:
        return f"{SOURCES_HEADING}\n\n{_UNAVAILABLE_NOTE}"

    lines = [SOURCES_HEADING, ""]
    for source in sources:
        title = (source.get("title") or "").strip() or "Untitled source"
        url = (source.get("url") or "").strip()
        entry = f"- [{title}]({url})"
        details = [
            part
            for part in (
                (source.get("publisher") or "").strip(),
                short_date(source.get("date")),
            )
            if part
        ]
        if details:
            entry += ", " + ", ".join(details)
        lines.append(entry)
    return "\n".join(lines)


def split_article_and_sources(body_markdown: str) -> Tuple[str, Optional[str]]:
    """Split a rendered body into (article_body, sources_section_or_None).

    The split point is the first line that is exactly a '## Sources' H2. Any
    earlier occurrence of the same phrase inside prose is not a heading match
    because the regex requires the heading to start the line.
    """
    match = _HEADING_RE.search(body_markdown)
    if not match:
        return body_markdown.strip(), None
    article = body_markdown[: match.start()].strip()
    section = body_markdown[match.start():].strip()
    return article, section


def strip_sources_section(body_markdown: str) -> str:
    """Remove any model-authored Sources section so ours is authoritative."""
    article, _ = split_article_and_sources(body_markdown)
    return article


def extract_links(text: str) -> List[str]:
    return _LINK_RE.findall(text or "")


def has_visible_sources(section_text: Optional[str]) -> bool:
    if not section_text:
        return False
    return bool(extract_links(section_text))
