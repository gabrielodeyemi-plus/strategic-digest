"""Failure-isolated orchestration for blog transformation and publishing."""

from pathlib import Path
from typing import Optional

from blog.config import BlogConfig
from blog.models import PublishResult
from blog.publishers import PublishStateStore, WebsiteBlogPublisher
from blog.quality import BlogQualityGate
from blog.transformer import BlogArticleTransformer
from digest_models import Digest


class BlogPublishingService:
    def __init__(
        self,
        config: BlogConfig,
        transformer=None,
        quality_gate=None,
        publisher=None,
        state_store: Optional[PublishStateStore] = None,
    ):
        self.config = config
        self.state_store = state_store or PublishStateStore(config.output_dir)
        self.transformer = transformer or BlogArticleTransformer(config)
        self.quality_gate = quality_gate or BlogQualityGate(config)
        self.publisher = publisher or WebsiteBlogPublisher(
            config, self.state_store
        )

    def publish(self, digest: Digest) -> PublishResult:
        day = digest.digest_date.isoformat()
        existing = self.state_store.get(day)
        if existing and self.config.existing_post_action == "skip":
            return PublishResult(
                status=existing.get("publish_status", "draft"),
                canonical_url=existing.get("canonical_url", ""),
                artifact_path=Path(existing["artifact_path"])
                if existing.get("artifact_path")
                else None,
                skipped=True,
                publisher=existing.get("publisher", "local"),
                message=f"Post for {day} already exists; skipped before transformation.",
            )

        revision_issues = []
        for _attempt in range(self.config.maximum_attempts):
            try:
                post = self.transformer.transform(digest, revision_issues)
                report = self.quality_gate.evaluate(post, digest)
            except Exception as exc:
                revision_issues = [
                    f"Transformation or quality review error: {exc}"
                ]
                continue
            if report.passed:
                result = self.publisher.publish(post)
                metadata = self.state_store.get(day)
                if metadata:
                    metadata["quality_gate_status"] = "passed"
                    self.state_store.save(day, metadata)
                return result
            revision_issues = report.issues

        raise RuntimeError(
            "Blog article failed the quality gate: " + "; ".join(revision_issues)
        )


def publish_digest_safely(
    digest: Digest,
    config: Optional[BlogConfig] = None,
) -> Optional[PublishResult]:
    """Publish without ever breaking the email/Notion digest run."""
    try:
        active_config = config or BlogConfig.from_env()
    except Exception as exc:
        print(f"  Blog configuration failed: {exc}")
        return None

    if not active_config.enabled:
        print("  Blog publishing disabled")
        return None

    store = PublishStateStore(active_config.output_dir)
    try:
        result = BlogPublishingService(
            active_config, state_store=store
        ).publish(digest)
        print(f"  {result.message}")
        return result
    except Exception as exc:
        try:
            store.record_failure(
                digest.digest_date.isoformat(), digest.digest_id, str(exc)
            )
        except Exception as state_exc:
            print(f"  Blog publish state could not be saved: {state_exc}")
        print(f"  Blog publishing failed: {exc}")
        print("  Email and Notion delivery are unaffected.")
        return None
