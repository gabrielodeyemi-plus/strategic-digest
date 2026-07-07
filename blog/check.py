"""Non-mutating preflight readiness check for a generated blog post.

`blog:check` answers one question -- is this draft ready to approve and
publish -- without touching any file. It deliberately reuses the exact same
helpers `approve_blog_post` uses (source readiness, quality-gate metadata,
website path resolution) so this command and `blog:approve --dry-run` can
never disagree about whether a post is ready.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

import yaml

from blog.approval import (
    ApprovalError,
    _FRONTMATTER,
    _evaluate_metadata_consistency,
    _evaluate_quality_metadata,
    _evaluate_sources_readiness,
    _locate_source,
    _parse_frontmatter_date,
    _resolve_slug,
    _resolve_website_paths,
)
from blog.config import BlogConfig
from blog.publishers import PublishStateStore
from blog.sources import split_article_and_sources

_WORD_RE = re.compile(r"\b[\w’'-]+\b")
_WORDS_PER_MINUTE = 200


@dataclass(frozen=True)
class CheckItem:
    passed: bool
    level: str  # "block" or "warn"
    message: str


@dataclass(frozen=True)
class CheckResult:
    requested_date: date
    fatal_error: Optional[str] = None
    title: str = ""
    slug: str = ""
    status: str = ""
    word_count: int = 0
    read_minutes: int = 0
    source_path: Optional[Path] = None
    destination_path: Optional[Path] = None
    website_local_url: str = ""
    sources_frontmatter_count: int = 0
    sources_required_minimum: int = 0
    content_items: List[CheckItem] = field(default_factory=list)
    sources_items: List[CheckItem] = field(default_factory=list)
    website_items: List[CheckItem] = field(default_factory=list)

    @property
    def all_items(self) -> List[CheckItem]:
        return [*self.content_items, *self.sources_items, *self.website_items]

    @property
    def blockers(self) -> List[str]:
        if self.fatal_error:
            return [self.fatal_error]
        return [item.message for item in self.all_items if not item.passed]

    @property
    def warnings(self) -> List[str]:
        return [
            item.message
            for item in self.all_items
            if item.passed and item.level == "warn_flag"
        ]

    @property
    def ready(self) -> bool:
        return not self.blockers

    @property
    def exit_code(self) -> int:
        return 0 if self.ready else 2

    @property
    def result_label(self) -> str:
        if not self.ready:
            return "BLOCKED"
        if self.warnings:
            return "READY with warnings"
        return "READY"


def _pass(message: str) -> CheckItem:
    return CheckItem(passed=True, level="info", message=message)


def _fail(message: str) -> CheckItem:
    return CheckItem(passed=False, level="block", message=message)


def _warn(message: str) -> CheckItem:
    """A non-blocking, always-surfaced advisory item."""
    return CheckItem(passed=True, level="warn_flag", message=message)


def run_check(requested_date: date, config: BlogConfig) -> CheckResult:
    """Compute a full readiness report without modifying any file or state."""
    try:
        source_path = _locate_source(config.output_dir, requested_date)
    except ApprovalError as exc:
        return CheckResult(requested_date=requested_date, fatal_error=str(exc))

    markdown = source_path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(markdown)
    if not match:
        return CheckResult(
            requested_date=requested_date,
            fatal_error=f"{source_path.name} has no valid YAML frontmatter.",
            source_path=source_path,
        )
    try:
        frontmatter = yaml.safe_load(match.group("yaml"))
    except yaml.YAMLError as exc:
        return CheckResult(
            requested_date=requested_date,
            fatal_error=f"{source_path.name} has invalid YAML frontmatter: {exc}",
            source_path=source_path,
        )
    if not isinstance(frontmatter, dict):
        return CheckResult(
            requested_date=requested_date,
            fatal_error=f"{source_path.name} frontmatter must be an object.",
            source_path=source_path,
        )

    body = markdown[match.end("after"):]
    article_body, sources_section = split_article_and_sources(body)

    content_items: List[CheckItem] = []

    title = str(frontmatter.get("title") or "").strip()
    content_items.append(
        _pass("title present") if title else _fail("title is missing or empty")
    )

    author = str(frontmatter.get("author") or "").strip()
    content_items.append(
        _pass("author present") if author else _fail("author is missing or empty")
    )

    try:
        slug = _resolve_slug(frontmatter, source_path, requested_date)
        content_items.append(_pass("slug valid"))
    except ApprovalError as exc:
        slug = ""
        content_items.append(_fail(str(exc)))

    frontmatter_date = frontmatter.get("date")
    if frontmatter_date is None:
        content_items.append(_fail("date is missing from frontmatter"))
    else:
        try:
            parsed_date = _parse_frontmatter_date(frontmatter_date, source_path)
            if parsed_date == requested_date:
                content_items.append(_pass("date matches requested date"))
            else:
                content_items.append(
                    _fail(
                        f"frontmatter date {parsed_date.isoformat()} does not "
                        f"match requested date {requested_date.isoformat()}"
                    )
                )
        except ApprovalError as exc:
            content_items.append(_fail(str(exc)))

    status = str(frontmatter.get("status") or "").strip().lower()
    if status in {"draft", "published"}:
        content_items.append(_pass(f"status is {status}"))
    else:
        content_items.append(
            _fail(f'status must be "draft" or "published", not "{status or "missing"}"')
        )
    already_published = status == "published"

    excerpt = str(frontmatter.get("excerpt") or "").strip()
    subtitle = str(frontmatter.get("subtitle") or "").strip()
    if excerpt or subtitle:
        content_items.append(_pass("excerpt or subtitle present"))
    else:
        content_items.append(_fail("excerpt or subtitle is missing"))

    tags = frontmatter.get("tags")
    if isinstance(tags, list) and any(str(tag).strip() for tag in tags):
        content_items.append(_pass(f"tags present ({len(tags)})"))
    else:
        content_items.append(_fail("tags are missing or empty"))

    word_count = len(_WORD_RE.findall(article_body))
    if word_count >= 40:
        content_items.append(_pass("article body present"))
    else:
        content_items.append(_fail("article body is missing or too thin"))

    state_store = PublishStateStore(config.output_dir)
    metadata = state_store.get(requested_date.isoformat())
    quality_evaluation = _evaluate_quality_metadata(metadata)
    consistency_evaluation = (
        _evaluate_metadata_consistency(metadata, source_path, title, slug)
        if quality_evaluation["passed"]
        else {"passed": True, "failures": []}
    )
    if quality_evaluation["passed"] and consistency_evaluation["passed"]:
        content_items.append(_pass("quality gate passed"))
    else:
        message = (quality_evaluation["failures"] + consistency_evaluation["failures"])[0]
        content_items.append(_fail(f"quality gate not passed: {message}"))

    if already_published:
        content_items.append(
            _warn(
                'post status is already "published"; re-approving will '
                "re-copy over the live file unless you explicitly intend that"
            )
        )

    sources_items: List[CheckItem] = []
    raw_sources = frontmatter.get("sources")
    structured_present = isinstance(raw_sources, list) and len(raw_sources) > 0
    sources_items.append(
        _pass("structured frontmatter sources present")
        if structured_present
        else _fail("structured frontmatter sources are missing")
    )

    sources_readiness = _evaluate_sources_readiness(frontmatter, body)
    valid_count = sources_readiness["frontmatter_count"]
    if valid_count > 0:
        sources_items.append(_pass(f"{valid_count} valid source URL(s)"))
    else:
        sources_items.append(_fail("no valid source URLs found in frontmatter"))

    if sources_readiness["visible_present"]:
        sources_items.append(_pass('visible "## Sources" section present'))
    else:
        sources_items.append(_fail('visible "## Sources" section is missing'))

    required_minimum = sources_readiness["required_minimum"]
    if sources_readiness["coverage_pass"]:
        sources_items.append(
            _pass(f"source coverage met: {valid_count} valid, {required_minimum} expected")
        )
    else:
        sources_items.append(
            _fail(
                f"source coverage below threshold: {valid_count} valid, "
                f"{required_minimum} expected"
            )
        )

    website_items: List[CheckItem] = []
    destination_path: Optional[Path] = None
    website_local_url = ""
    try:
        _, _, destination_path = _resolve_website_paths(config, source_path)
        website_items.append(_pass("website repo exists"))
        website_items.append(_pass("website content directory exists"))
        website_local_url = f"http://localhost:5173/blog/{slug or source_path.stem}"
        if destination_path.exists():
            website_items.append(
                _warn("destination file already exists; approval requires --force")
            )
    except ApprovalError as exc:
        text = str(exc)
        if "content directory" in text.lower() or "resolves outside" in text.lower():
            website_items.append(_pass("website repo exists"))
            website_items.append(_fail(text))
        else:
            website_items.append(_fail(text))
            website_items.append(
                _fail("website content directory cannot be checked: repo missing")
            )

    read_minutes = max(1, round(word_count / _WORDS_PER_MINUTE))

    return CheckResult(
        requested_date=requested_date,
        title=title,
        slug=slug,
        status=status,
        word_count=word_count,
        read_minutes=read_minutes,
        source_path=source_path,
        destination_path=destination_path,
        website_local_url=website_local_url,
        sources_frontmatter_count=valid_count,
        sources_required_minimum=required_minimum,
        content_items=content_items,
        sources_items=sources_items,
        website_items=website_items,
    )


def render_report(result: CheckResult) -> str:
    lines = ["── Blog readiness check ───────────────────────────────"]
    if result.fatal_error:
        lines.append(f"Date: {result.requested_date.isoformat()}")
        lines.append("")
        lines.append(f"FAIL {result.fatal_error}")
        lines.append("")
        lines.append(f"Result: {result.result_label}")
        return "\n".join(lines)

    lines.append(f"Title: {result.title or '(missing)'}")
    lines.append(f"Date: {result.requested_date.isoformat()}")
    lines.append(f"Slug: {result.slug or '(missing)'}")
    lines.append(f"Status: {result.status or '(missing)'}")
    lines.append(f"Word count: {result.word_count:,}")
    lines.append(f"Read time: {result.read_minutes} min")
    if result.source_path:
        lines.append(f"Source file: {result.source_path}")
    if result.destination_path:
        lines.append(f"Website destination: {result.destination_path}")
    if result.website_local_url:
        lines.append(f"Local website URL: {result.website_local_url}")
    lines.append("")

    lines.append("Content:")
    for item in result.content_items:
        lines.append(f"{_tag(item)} {item.message}")
    lines.append("")

    lines.append("Sources:")
    for item in result.sources_items:
        lines.append(f"{_tag(item)} {item.message}")
    lines.append("")

    lines.append("Website target:")
    for item in result.website_items:
        lines.append(f"{_tag(item)} {item.message}")
    lines.append("")

    lines.append(f"Result: {result.result_label}")
    return "\n".join(lines)


def _tag(item: CheckItem) -> str:
    if not item.passed:
        return "FAIL"
    if item.level == "warn_flag":
        return "WARN"
    return "PASS"
