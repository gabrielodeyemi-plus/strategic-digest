"""Blog publisher adapters with local fallback and idempotent state."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol

from blog.config import BlogConfig
from blog.models import BlogPost, PublishResult


class BlogPublisher(Protocol):
    """Interface implemented by every blog output adapter."""

    def publish(self, post: BlogPost) -> PublishResult:
        ...


class PublishStateStore:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.path = output_dir / "publish-state.json"

    def get(self, source_digest_date: str) -> Optional[dict]:
        return self._read().get(source_digest_date)

    def save(self, source_digest_date: str, metadata: dict) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        state = self._read()
        state[source_digest_date] = metadata
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def record_failure(self, source_digest_date: str, source_digest_id: str, error: str):
        existing = self.get(source_digest_date)
        if existing and existing.get("publish_status") in {"draft", "published"}:
            return
        self.save(source_digest_date, {
            "title": "",
            "slug": "",
            "date": source_digest_date,
            "source_digest_date": source_digest_date,
            "source_digest_id": source_digest_id,
            "canonical_url": "",
            "publish_status": "failed",
            "quality_gate_status": "failed",
            "publisher": "",
            "artifact_path": "",
            "error": error,
            "updated_at": _now(),
        })

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError(f"Cannot read blog publish state: {exc}") from exc


class LocalBlogPublisher:
    """Write a portable Markdown artifact and local publication metadata."""

    def __init__(
        self,
        config: BlogConfig,
        state_store: Optional[PublishStateStore] = None,
    ):
        self.config = config
        self.state_store = state_store or PublishStateStore(config.output_dir)

    def publish(self, post: BlogPost) -> PublishResult:
        day = post.source_digest_date.isoformat()
        existing = self.state_store.get(day)
        if existing and self.config.existing_post_action == "skip":
            return PublishResult(
                status=existing.get("publish_status", "draft"),
                canonical_url=existing.get("canonical_url", post.canonical_url),
                artifact_path=Path(existing["artifact_path"])
                if existing.get("artifact_path")
                else None,
                skipped=True,
                publisher=existing.get("publisher", "local"),
                message=f"Post for {day} already exists; skipped.",
            )

        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        artifact = self.config.output_dir / f"{day}-{post.slug}.md"
        _remove_replaced_artifact(existing, artifact, self.config.output_dir)
        temporary = artifact.with_suffix(".md.tmp")
        temporary.write_text(post.to_markdown(), encoding="utf-8")
        temporary.replace(artifact)

        result = PublishResult(
            status=post.status,
            canonical_url=post.canonical_url,
            artifact_path=artifact.resolve(),
            publisher="local",
            message=f"Wrote local blog artifact to {artifact}.",
        )
        self.state_store.save(day, _metadata(post, result))
        return result


class RepositoryBlogPublisher:
    """Write Markdown into a website repository that has a content pipeline.

    This adapter intentionally does not commit, push, or deploy. Those external
    state changes must be configured separately after the website can render the
    content directory.
    """

    def __init__(
        self,
        config: BlogConfig,
        state_store: Optional[PublishStateStore] = None,
    ):
        self.config = config
        self.state_store = state_store or PublishStateStore(config.output_dir)

    def publish(self, post: BlogPost) -> PublishResult:
        day = post.source_digest_date.isoformat()
        existing = self.state_store.get(day)
        if existing and self.config.existing_post_action == "skip":
            return PublishResult(
                status=existing.get("publish_status", "draft"),
                canonical_url=existing.get("canonical_url", post.canonical_url),
                artifact_path=Path(existing["artifact_path"])
                if existing.get("artifact_path")
                else None,
                skipped=True,
                publisher=existing.get("publisher", "repository"),
                message=f"Post for {day} already exists; skipped.",
            )

        repo = self.config.website_repo_path.expanduser().resolve()
        if not (repo / ".git").exists():
            raise ValueError(f"WEBSITE_REPO_PATH is not a Git repository: {repo}")
        destination = repo / self.config.website_content_dir
        destination.mkdir(parents=True, exist_ok=True)
        artifact = destination / f"{post.source_digest_date.isoformat()}-{post.slug}.md"
        _remove_replaced_artifact(existing, artifact, destination)
        temporary = artifact.with_suffix(".md.tmp")
        temporary.write_text(post.to_markdown(), encoding="utf-8")
        temporary.replace(artifact)
        result = PublishResult(
            status=post.status,
            canonical_url=post.canonical_url,
            artifact_path=artifact,
            publisher="repository",
            message=(
                f"Wrote website repository artifact to {artifact}. "
                "Commit/deploy is not automatic."
            ),
        )
        self.state_store.save(
            day, _metadata(post, result)
        )
        return result


class WebsiteBlogPublisher:
    """Select the configured publisher and fall back to a local draft."""

    def __init__(
        self,
        config: BlogConfig,
        state_store: Optional[PublishStateStore] = None,
    ):
        self.config = config
        self.state_store = state_store or PublishStateStore(config.output_dir)

    def publish(self, post: BlogPost) -> PublishResult:
        if self.config.mode == "local":
            return LocalBlogPublisher(self.config, self.state_store).publish(post)
        if self.config.approval_required:
            post.status = "draft"
            result = LocalBlogPublisher(
                self.config, self.state_store
            ).publish(post)
            return PublishResult(
                status=result.status,
                canonical_url=result.canonical_url,
                artifact_path=result.artifact_path,
                skipped=result.skipped,
                publisher="local-approval-required",
                message=(
                    "Approval is required; wrote a local draft instead of "
                    "copying it to the website repository."
                ),
            )
        try:
            return RepositoryBlogPublisher(
                self.config, self.state_store
            ).publish(post)
        except Exception as exc:
            post.status = "draft"
            result = LocalBlogPublisher(
                self.config, self.state_store
            ).publish(post)
            return PublishResult(
                status=result.status,
                canonical_url=result.canonical_url,
                artifact_path=result.artifact_path,
                skipped=result.skipped,
                publisher="local-fallback",
                message=f"Repository publish failed ({exc}); {result.message}",
            )


def _metadata(post: BlogPost, result: PublishResult) -> dict:
    return {
        "title": post.title,
        "slug": post.slug,
        "date": post.date.isoformat(),
        "source_digest_date": post.source_digest_date.isoformat(),
        "source_digest_id": post.source_digest_id,
        "canonical_url": post.canonical_url,
        "publish_status": result.status,
        "publisher": result.publisher,
        "artifact_path": str(result.artifact_path) if result.artifact_path else "",
        "updated_at": _now(),
    }


def _remove_replaced_artifact(
    existing: Optional[dict],
    replacement: Path,
    allowed_directory: Path,
) -> None:
    """Remove only an older managed Markdown file superseded by an update."""
    if not existing or not existing.get("artifact_path"):
        return
    previous = Path(existing["artifact_path"]).expanduser().resolve()
    replacement = replacement.resolve()
    allowed_directory = allowed_directory.expanduser().resolve()
    if (
        previous != replacement
        and previous.parent == allowed_directory
        and previous.suffix == ".md"
        and previous.exists()
    ):
        previous.unlink()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
