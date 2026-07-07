"""Environment-backed blog publishing configuration."""

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class BlogConfig:
    enabled: bool = True
    mode: str = "local"
    author: str = "Gabriel Odeyemi"
    base_url: str = "https://gabrielodeyemi.com"
    output_dir: Path = Path("./output/blog")
    default_status: str = "draft"
    existing_post_action: str = "skip"
    minimum_words: int = 900
    maximum_words: int = 1500
    quality_review_enabled: bool = True
    maximum_attempts: int = 2
    website_repo_path: Path = Path(
        "/Users/olugbengaodeyemi/Downloads/personalwebsite"
    )
    website_content_dir: str = "src/content/blog"
    approval_required: bool = True
    pr_enabled: bool = True
    pr_base_branch: str = "main"
    pr_branch_prefix: str = "strategic-digest"
    pr_run_build: bool = True

    @classmethod
    def from_env(cls) -> "BlogConfig":
        repo_path = (
            os.environ.get("BLOG_WEBSITE_REPO_PATH")
            or os.environ.get("WEBSITE_REPO_PATH")
            or "/Users/olugbengaodeyemi/Downloads/personalwebsite"
        ).strip()
        config = cls(
            enabled=_bool("BLOG_PUBLISH_ENABLED", True),
            mode=os.environ.get("BLOG_PUBLISH_MODE", "local").strip().lower(),
            author=os.environ.get("BLOG_AUTHOR", "Gabriel Odeyemi").strip(),
            base_url=os.environ.get(
                "BLOG_BASE_URL", "https://gabrielodeyemi.com"
            ).strip().rstrip("/"),
            output_dir=Path(os.environ.get("BLOG_OUTPUT_DIR", "./output/blog")),
            default_status=os.environ.get(
                "BLOG_DEFAULT_STATUS", "draft"
            ).strip().lower(),
            existing_post_action=os.environ.get(
                "BLOG_EXISTING_POST_ACTION", "skip"
            ).strip().lower(),
            minimum_words=int(os.environ.get("BLOG_MIN_WORDS", "900")),
            maximum_words=int(os.environ.get("BLOG_MAX_WORDS", "1500")),
            quality_review_enabled=_bool("BLOG_QUALITY_REVIEW_ENABLED", True),
            maximum_attempts=int(os.environ.get("BLOG_MAX_ATTEMPTS", "2")),
            website_repo_path=Path(repo_path).expanduser(),
            website_content_dir=os.environ.get(
                "BLOG_WEBSITE_CONTENT_DIR", "src/content/blog"
            ).strip(),
            approval_required=_bool("BLOG_APPROVAL_REQUIRED", True),
            pr_enabled=_bool("BLOG_PR_ENABLED", True),
            pr_base_branch=os.environ.get("BLOG_PR_BASE_BRANCH", "main").strip(),
            pr_branch_prefix=os.environ.get(
                "BLOG_PR_BRANCH_PREFIX", "strategic-digest"
            ).strip(),
            pr_run_build=_bool("BLOG_PR_RUN_BUILD", True),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.mode not in {"local", "repository"}:
            raise ValueError(
                "BLOG_PUBLISH_MODE must be 'local' or 'repository'. "
                "CMS/API publishing is not configured."
            )
        if self.default_status not in {"draft", "published"}:
            raise ValueError("BLOG_DEFAULT_STATUS must be 'draft' or 'published'")
        if self.existing_post_action not in {"skip", "update"}:
            raise ValueError("BLOG_EXISTING_POST_ACTION must be 'skip' or 'update'")
        if self.minimum_words < 1 or self.maximum_words < self.minimum_words:
            raise ValueError("BLOG_MIN_WORDS and BLOG_MAX_WORDS are invalid")
        if self.maximum_attempts < 1:
            raise ValueError("BLOG_MAX_ATTEMPTS must be at least 1")
        content_dir = Path(self.website_content_dir)
        if (
            not self.website_content_dir
            or content_dir.is_absolute()
            or ".." in content_dir.parts
        ):
            raise ValueError(
                "BLOG_WEBSITE_CONTENT_DIR must be a relative path inside "
                "BLOG_WEBSITE_REPO_PATH"
            )
        if not self.pr_base_branch:
            raise ValueError("BLOG_PR_BASE_BRANCH must not be empty")
        if not self.pr_branch_prefix or "/" in self.pr_branch_prefix.strip("/"):
            raise ValueError(
                "BLOG_PR_BRANCH_PREFIX must be a single path segment, e.g. "
                "'strategic-digest'"
            )
