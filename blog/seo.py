"""Controlled vocabulary and validation for blog discoverability metadata.

This module owns the "what does the website need to build topic authority"
contract: a fixed list of topic clusters, a fixed universe of internal link
targets, and pure validation of the SEO/discoverability frontmatter fields
(`seo_title`, `topic_cluster`, `primary_keyword`, `secondary_keywords`,
`internal_link_targets`, `suggested_related_posts`).

Rollout-safety policy (see README "SEO metadata" section for the full
rationale): a field being *missing* is a warning, never a blocker, so every
post generated before this feature existed keeps passing `blog:check` and
`blog:approve`. A field being *present but wrong* -- an invalid topic
cluster, a malformed entry, or a URL that was not in an allowed list -- is a
hard blocker, because that is invented or structurally broken metadata, not
an incomplete draft.

Nothing in this module performs network calls. `known_blog_posts` reads the
local website content directory and only returns posts already marked
published, matching the project's existing "never invent a related post" rule.
"""

from pathlib import Path
from typing import Iterable, List, Optional

from blog.frontmatter import FrontmatterError, parse_markdown_frontmatter

TOPIC_CLUSTERS = (
    "AI Operating Systems",
    "AI Agents",
    "Strategy & Operations",
    "AI Governance",
    "Logistics & Workflow Automation",
    "Strategic Intelligence",
    "Markets & Business Models",
    "Public Sector & Policy",
    "Leadership & Organizational Change",
    "Corporate Strategy",
    "Technology Infrastructure",
)

INTERNAL_LINK_TARGET_UNIVERSE = (
    "/",
    "/blog",
    "/ai-consulting",
    "/projects/vigil",
    "/projects/strategicdigest",
    "/projects/churnagent",
    "/blog/tag/artificial-intelligence",
    "/blog/tag/enterprise-governance",
    "/blog/tag/corporate-strategy",
    "/blog/tag/strategy-operations",
    "/blog/tag/logistics-workflow-automation",
    "/blog/tag/strategic-intelligence",
)

MIN_SECONDARY_KEYWORDS = 3
MAX_SECONDARY_KEYWORDS = 7
MIN_INTERNAL_LINK_TARGETS = 1
MAX_INTERNAL_LINK_TARGETS = 4
MAX_SUGGESTED_RELATED_POSTS = 3

SITE_BASE_URL = "https://gabrielodeyemi.com"

def path_only(url: str) -> str:
    """Strips *only* our own site's base URL prefix so "/blog/x" and
    "https://gabrielodeyemi.com/blog/x" compare equal. Deliberately does not
    strip an arbitrary scheme+host: an external URL like
    "https://not-allowed.example.com" must stay recognizably external (and
    therefore fail the allow-list check) rather than collapsing to "/" just
    because it has no path component.
    """
    stripped = (url or "").strip()
    if not stripped:
        return "/"
    if stripped.startswith(SITE_BASE_URL):
        remainder = stripped[len(SITE_BASE_URL):]
        return remainder or "/"
    return stripped


def is_valid_topic_cluster(value: str) -> bool:
    return value in TOPIC_CLUSTERS


def is_allowed_internal_link_url(url: str) -> bool:
    return path_only(url) in INTERNAL_LINK_TARGET_UNIVERSE


def known_blog_posts(output_dir: Path, *, exclude_path: Optional[Path] = None) -> List[dict]:
    """Scans website blog content for published posts.

    Returns [{"title", "url"}] using each post's frontmatter `title` and
    `canonical_url` (or a `/blog/{slug}` fallback). Unreadable or malformed
    files are skipped rather than raising, since this is inventory for prompt
    grounding, not a gate in itself. Drafts are excluded so the transformer
    cannot recommend current or future posts that are not published.
    """
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        return []
    exclude = exclude_path.resolve() if exclude_path else None

    posts = []
    for path in sorted(output_dir.glob("*.md")):
        if exclude and path.resolve() == exclude:
            continue
        try:
            raw = path.read_text(encoding="utf-8")
            data, _ = parse_markdown_frontmatter(
                raw, path, action="building related-post inventory"
            )
        except (OSError, FrontmatterError):
            continue

        if str(data.get("status") or "").strip().lower() != "published":
            continue
        title = str(data.get("title") or "").strip()
        slug = str(data.get("slug") or "").strip()
        canonical = str(data.get("canonical_url") or "").strip()
        url = path_only(canonical) if canonical else (f"/blog/{slug}" if slug else "")
        if title and url:
            posts.append({"title": title, "url": url})
    return posts


def known_blog_post_urls(output_dir: Path, *, exclude_path: Optional[Path] = None) -> set:
    return {post["url"] for post in known_blog_posts(output_dir, exclude_path=exclude_path)}


def evaluate_seo_metadata(frontmatter: dict, known_post_urls: Iterable[str] = ()) -> dict:
    """Pure validation of the SEO/discoverability frontmatter fields.

    Returns {"warnings": [...], "blockers": [...]}. See the module docstring
    for the warn-vs-block policy. Never raises: malformed input becomes a
    blocker message, not an exception.
    """
    known_post_urls = set(known_post_urls)
    warnings: List[str] = []
    blockers: List[str] = []

    seo_title = frontmatter.get("seo_title")
    if not (isinstance(seo_title, str) and seo_title.strip()):
        warnings.append("seo_title is missing.")

    topic_cluster = frontmatter.get("topic_cluster")
    if topic_cluster is None or (isinstance(topic_cluster, str) and not topic_cluster.strip()):
        warnings.append("topic_cluster is missing.")
    elif not isinstance(topic_cluster, str):
        blockers.append("topic_cluster is malformed: it must be a string.")
    elif not is_valid_topic_cluster(topic_cluster):
        blockers.append(
            f'topic_cluster "{topic_cluster}" is not one of the controlled values: '
            + ", ".join(TOPIC_CLUSTERS)
        )

    primary_keyword = frontmatter.get("primary_keyword")
    if not (isinstance(primary_keyword, str) and primary_keyword.strip()):
        warnings.append("primary_keyword is missing.")

    secondary_keywords = frontmatter.get("secondary_keywords")
    if secondary_keywords is None or secondary_keywords == []:
        warnings.append("secondary_keywords is missing.")
    elif not (
        isinstance(secondary_keywords, list)
        and all(isinstance(kw, str) for kw in secondary_keywords)
    ):
        blockers.append(
            "secondary_keywords is malformed: it must be a list of strings."
        )
    elif not (MIN_SECONDARY_KEYWORDS <= len(secondary_keywords) <= MAX_SECONDARY_KEYWORDS):
        warnings.append(
            f"secondary_keywords has {len(secondary_keywords)} entries; expected "
            f"{MIN_SECONDARY_KEYWORDS} to {MAX_SECONDARY_KEYWORDS}."
        )

    warnings.extend(
        _evaluate_link_list(
            frontmatter.get("internal_link_targets"),
            field_name="internal_link_targets",
            required_keys=("label", "url"),
            min_count=MIN_INTERNAL_LINK_TARGETS,
            max_count=MAX_INTERNAL_LINK_TARGETS,
            blockers=blockers,
            url_is_allowed=is_allowed_internal_link_url,
            invalid_url_message=(
                "internal_link_targets includes a URL outside the allowed "
                "target universe: {url}"
            ),
        )
    )

    warnings.extend(
        _evaluate_link_list(
            frontmatter.get("suggested_related_posts"),
            field_name="suggested_related_posts",
            required_keys=("title", "url"),
            min_count=0,
            max_count=MAX_SUGGESTED_RELATED_POSTS,
            blockers=blockers,
            url_is_allowed=lambda url: path_only(url) in known_post_urls,
            invalid_url_message=(
                "suggested_related_posts references a post that is not a "
                "known blog post: {url}"
            ),
            optional=True,
        )
    )

    return {"warnings": warnings, "blockers": blockers}


def _evaluate_link_list(
    value,
    *,
    field_name: str,
    required_keys: tuple,
    min_count: int,
    max_count: int,
    blockers: List[str],
    url_is_allowed,
    invalid_url_message: str,
    optional: bool = False,
) -> List[str]:
    """Shared validator for internal_link_targets and suggested_related_posts:
    both are lists of {label|title, url, reason?, status?} objects."""
    warnings: List[str] = []

    if value is None or value == []:
        if not optional:
            warnings.append(f"{field_name} is missing.")
        return warnings

    if not isinstance(value, list):
        blockers.append(f"{field_name} is malformed: it must be a list.")
        return warnings

    for item in value:
        if not isinstance(item, dict):
            blockers.append(
                f"{field_name} is malformed: each entry must be an object, got {item!r}."
            )
            continue
        for key in required_keys:
            if not (isinstance(item.get(key), str) and item.get(key).strip()):
                blockers.append(
                    f'{field_name} entry is malformed: missing or empty "{key}".'
                )
        url = item.get("url")
        if isinstance(url, str) and url.strip() and not url_is_allowed(url):
            blockers.append(invalid_url_message.format(url=url))

    if not (min_count <= len(value) <= max_count):
        warnings.append(
            f"{field_name} has {len(value)} entries; expected {min_count} to {max_count}."
        )

    return warnings
