"""Explicit approval and cross-repository handoff for reviewed blog posts."""

import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from blog.config import BlogConfig
from blog.publishers import PublishStateStore
from blog.sources import has_visible_sources, is_valid_url, split_article_and_sources


_FRONTMATTER = re.compile(
    r"\A---\r?\n(?P<yaml>[\s\S]*?)\r?\n---(?P<after>\r?\n|\Z)"
)
_STATUS_LINE = re.compile(r"(?m)^[ \t]*status[ \t]*:[^\r\n]*$")
_VALID_STATE_STATUSES = {"draft", "published", "copied_to_website_repo"}


class ApprovalError(RuntimeError):
    """A safe, user-actionable approval failure."""


@dataclass(frozen=True)
class ApprovalResult:
    requested_date: date
    title: str
    slug: str
    current_status: str
    source_path: Path
    destination_path: Path
    destination_exists: bool
    dry_run: bool
    overwritten: bool = False
    approved_at: str = ""
    sources_frontmatter_count: int = 0
    sources_visible_present: bool = False
    sources_required_minimum: int = 0
    sources_coverage_pass: bool = False
    sources_eligible: bool = False


def approve_blog_post(
    requested_date: date,
    config: BlogConfig,
    *,
    dry_run: bool = False,
    force: bool = False,
    now: Optional[datetime] = None,
) -> ApprovalResult:
    """Validate, approve, copy, and record one generated blog post."""
    source_path = _locate_source(config.output_dir, requested_date)
    original = source_path.read_text(encoding="utf-8")
    frontmatter, updated = _validate_and_approve_markdown(
        original, source_path, requested_date
    )
    title = frontmatter["title"].strip()
    current_status = frontmatter["status"].strip().lower()
    slug = _resolve_slug(frontmatter, source_path, requested_date)
    sources_readiness = _evaluate_sources_readiness(frontmatter, original)

    state_store = PublishStateStore(config.output_dir)
    metadata = _quality_passed_metadata(
        state_store, requested_date, source_path, title, slug
    )

    repo_path, destination_dir, destination_path = _resolve_website_paths(
        config, source_path
    )

    destination_exists = destination_path.exists()
    if destination_exists and not force and not dry_run:
        raise ApprovalError(
            f"Destination already exists: {destination_path}. "
            "Use --force to overwrite it."
        )

    result = ApprovalResult(
        requested_date=requested_date,
        title=title,
        slug=slug,
        current_status=current_status,
        source_path=source_path.resolve(),
        destination_path=destination_path,
        destination_exists=destination_exists,
        dry_run=dry_run,
        overwritten=destination_exists and force,
        sources_frontmatter_count=sources_readiness["frontmatter_count"],
        sources_visible_present=sources_readiness["visible_present"],
        sources_required_minimum=sources_readiness["required_minimum"],
        sources_coverage_pass=sources_readiness["coverage_pass"],
        sources_eligible=sources_readiness["eligible"],
    )
    if dry_run:
        return result

    if not sources_readiness["eligible"]:
        raise ApprovalError("\n".join(sources_readiness["failures"]))

    approved_at = (now or datetime.now(timezone.utc)).astimezone(
        timezone.utc
    ).isoformat()
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination_original = (
        destination_path.read_text(encoding="utf-8")
        if destination_exists
        else None
    )

    try:
        _atomic_write(destination_path, updated)
        _atomic_write(source_path, updated)
        metadata.update({
            "approved_at": approved_at,
            "approved_file_path": str(source_path.resolve()),
            "website_repo_path": str(repo_path),
            "website_content_path": str(destination_path.resolve()),
            "website_slug": slug,
            "website_local_url": f"http://localhost:5173/blog/{slug}",
            "status": "copied_to_website_repo",
            "publish_status": "copied_to_website_repo",
            "updated_at": approved_at,
        })
        state_store.save(requested_date.isoformat(), metadata)
    except Exception as exc:
        _atomic_write(source_path, original)
        if destination_original is None:
            destination_path.unlink(missing_ok=True)
        else:
            _atomic_write(destination_path, destination_original)
        if isinstance(exc, ApprovalError):
            raise
        raise ApprovalError(f"Approval could not be completed: {exc}") from exc

    return ApprovalResult(
        requested_date=result.requested_date,
        title=result.title,
        slug=result.slug,
        current_status=result.current_status,
        source_path=result.source_path,
        destination_path=result.destination_path,
        destination_exists=result.destination_exists,
        dry_run=False,
        overwritten=result.overwritten,
        approved_at=approved_at,
        sources_frontmatter_count=result.sources_frontmatter_count,
        sources_visible_present=result.sources_visible_present,
        sources_required_minimum=result.sources_required_minimum,
        sources_coverage_pass=result.sources_coverage_pass,
        sources_eligible=result.sources_eligible,
    )


def _resolve_website_paths(
    config: BlogConfig, source_path: Path
) -> tuple[Path, Path, Path]:
    """Resolve and validate the website repo/content/destination paths.

    Shared by `approve_blog_post` and `blog:check` so both agree on exactly
    what "the website target" means and raise the same messages when it's
    missing or misconfigured.
    """
    repo_path = config.website_repo_path.expanduser().resolve()
    if not repo_path.is_dir():
        raise ApprovalError(
            f"Website repository does not exist: {repo_path}. "
            "Set BLOG_WEBSITE_REPO_PATH."
        )
    if not (repo_path / ".git").exists():
        raise ApprovalError(
            f"Website path is not a Git repository: {repo_path}."
        )
    destination_dir = (repo_path / config.website_content_dir).resolve()
    if repo_path != destination_dir and repo_path not in destination_dir.parents:
        raise ApprovalError(
            "BLOG_WEBSITE_CONTENT_DIR resolves outside BLOG_WEBSITE_REPO_PATH."
        )
    destination_path = destination_dir / source_path.name
    if destination_path.resolve() == source_path.resolve():
        raise ApprovalError("Source and destination paths must be different.")
    return repo_path, destination_dir, destination_path


def _locate_source(output_dir: Path, requested_date: date) -> Path:
    candidates = sorted(
        path
        for path in output_dir.expanduser().glob(
            f"{requested_date.isoformat()}-*.md"
        )
        if path.is_file()
    )
    if not candidates:
        raise ApprovalError(
            f"No generated blog post found for {requested_date.isoformat()} "
            f"in {output_dir}."
        )
    if len(candidates) > 1:
        names = ", ".join(path.name for path in candidates)
        raise ApprovalError(
            f"Expected exactly one post for {requested_date.isoformat()}, "
            f"found {len(candidates)}: {names}"
        )
    return candidates[0]


def _validate_and_approve_markdown(
    markdown: str,
    source_path: Path,
    requested_date: date,
) -> tuple[dict, str]:
    match = _FRONTMATTER.match(markdown)
    if not match:
        raise ApprovalError(f"{source_path.name} has no valid YAML frontmatter.")
    try:
        parsed = yaml.safe_load(match.group("yaml"))
    except yaml.YAMLError as exc:
        raise ApprovalError(
            f"{source_path.name} has invalid YAML frontmatter: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise ApprovalError(f"{source_path.name} frontmatter must be an object.")

    for field in ("title", "status"):
        if not isinstance(parsed.get(field), str) or not parsed[field].strip():
            raise ApprovalError(
                f'{source_path.name} is missing required frontmatter "{field}".'
            )
    if not isinstance(parsed.get("date"), (str, date)):
        raise ApprovalError(
            f'{source_path.name} is missing required frontmatter "date".'
        )

    post_date = _parse_frontmatter_date(parsed["date"], source_path)
    if post_date != requested_date:
        raise ApprovalError(
            f"Requested date {requested_date.isoformat()} does not match "
            f"frontmatter date {post_date.isoformat()}."
        )

    status = str(parsed["status"]).strip().lower()
    if status not in {"draft", "published"}:
        raise ApprovalError(
            f'{source_path.name} status must be "draft" or "published", '
            f'not "{status}".'
        )
    if not _STATUS_LINE.search(match.group("yaml")):
        raise ApprovalError(
            f'{source_path.name} is missing a writable "status" field.'
        )

    approved_yaml = _STATUS_LINE.sub(
        'status: "published"', match.group("yaml"), count=1
    )
    updated = (
        markdown[:match.start("yaml")]
        + approved_yaml
        + markdown[match.end("yaml"):]
    )
    return parsed, updated


def _evaluate_sources_readiness(frontmatter: dict, markdown: str) -> dict:
    """Compute source-coverage readiness purely from the on-disk post.

    Returns a dict describing what a human would see in the dry-run report
    (frontmatter_count, visible_present, required_minimum, coverage_pass,
    eligible) plus the exact "FAIL: ..." messages that block a real approval.
    """
    match = _FRONTMATTER.match(markdown)
    body = markdown[match.end("after"):] if match else markdown
    _, sources_section = split_article_and_sources(body)
    visible_present = has_visible_sources(sources_section)

    raw_sources = frontmatter.get("sources")
    frontmatter_sources = raw_sources if isinstance(raw_sources, list) else []
    valid_count = sum(
        1
        for item in frontmatter_sources
        if isinstance(item, dict) and is_valid_url(item.get("url"))
    )

    required_raw = frontmatter.get("minimum_sources_required")
    sources_missing = required_raw == 0
    try:
        required_minimum = (
            int(required_raw) if required_raw is not None else 3
        )
    except (TypeError, ValueError):
        required_minimum = 3

    failures = []
    if sources_missing:
        failures.append(
            "FAIL: Source metadata is unavailable for this digest "
            "(sources_missing); approval is blocked until sources exist."
        )
    if valid_count == 0:
        failures.append("FAIL: Blog post frontmatter has no valid source URLs.")
    if not visible_present:
        failures.append("FAIL: Blog post is missing visible Sources section.")

    coverage_pass = not sources_missing and valid_count >= required_minimum
    if not sources_missing and valid_count < required_minimum:
        failures.append(
            "FAIL: Source coverage below threshold: "
            f"{valid_count} valid sources found, {required_minimum} expected."
        )

    return {
        "frontmatter_count": valid_count,
        "visible_present": visible_present,
        "required_minimum": 0 if sources_missing else required_minimum,
        "coverage_pass": coverage_pass,
        "eligible": not failures,
        "failures": failures,
    }


def _parse_frontmatter_date(value, source_path: Path) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ApprovalError(
            f'{source_path.name} frontmatter "date" must be YYYY-MM-DD.'
        ) from exc


def _resolve_slug(
    frontmatter: dict,
    source_path: Path,
    requested_date: date,
) -> str:
    explicit = frontmatter.get("slug")
    if explicit is not None and not isinstance(explicit, str):
        raise ApprovalError(f'{source_path.name} frontmatter "slug" must be text.')
    candidate = (explicit or "").strip()
    if not candidate:
        prefix = f"{requested_date.isoformat()}-"
        candidate = source_path.stem
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix):]
    slug = re.sub(r"[^a-z0-9]+", "-", candidate.lower()).strip("-")
    if not slug:
        raise ApprovalError(
            f"{source_path.name} has no usable slug and one cannot be derived."
        )
    return slug


def _evaluate_quality_metadata(metadata: Optional[dict]) -> dict:
    """Pure, non-raising check of publish-state quality/status readiness.

    Returns {"exists", "state_status", "quality_gate_status", "passed",
    "failures"}. `blog:check` and `approve_blog_post` both call this so a
    post can never be reported ready by one and blocked by the other.
    """
    if not metadata:
        return {
            "exists": False,
            "state_status": "",
            "quality_gate_status": "",
            "passed": False,
            "failures": [
                "No publication metadata exists for this post, so a passed "
                "editorial quality gate cannot be verified."
            ],
        }
    state_status = str(
        metadata.get("publish_status") or metadata.get("status") or ""
    ).lower()
    quality_status = str(metadata.get("quality_gate_status") or "").lower()
    failures = []
    if state_status == "failed" or quality_status == "failed":
        failures.append(
            "This post failed the editorial quality review and cannot be approved."
        )
    elif quality_status and quality_status != "passed":
        failures.append(
            f'Editorial quality status is "{quality_status}", not "passed".'
        )
    elif state_status not in _VALID_STATE_STATUSES:
        failures.append(
            f'Publication metadata status "{state_status or "missing"}" '
            "is not eligible for approval."
        )
    return {
        "exists": True,
        "state_status": state_status,
        "quality_gate_status": quality_status,
        "passed": not failures,
        "failures": failures,
    }


def _evaluate_metadata_consistency(
    metadata: Optional[dict], source_path: Path, title: str, slug: str
) -> dict:
    """Pure, non-raising check that publish-state metadata matches the file."""
    if not metadata:
        return {"passed": True, "failures": []}
    failures = []
    artifact_path = metadata.get("artifact_path")
    if not artifact_path or Path(artifact_path).expanduser().resolve() != (
        source_path.resolve()
    ):
        failures.append(
            "Publication metadata does not match the generated artifact path."
        )
    if metadata.get("title") and metadata["title"] != title:
        failures.append("Publication metadata title does not match the post.")
    if metadata.get("slug") and metadata["slug"] != slug:
        failures.append("Publication metadata slug does not match the post.")
    return {"passed": not failures, "failures": failures}


def _quality_passed_metadata(
    state_store: PublishStateStore,
    requested_date: date,
    source_path: Path,
    title: str,
    slug: str,
) -> dict:
    metadata = state_store.get(requested_date.isoformat())
    evaluation = _evaluate_quality_metadata(metadata)
    if not evaluation["passed"]:
        raise ApprovalError(evaluation["failures"][0])

    consistency = _evaluate_metadata_consistency(metadata, source_path, title, slug)
    if not consistency["passed"]:
        raise ApprovalError(consistency["failures"][0])
    return dict(metadata)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
