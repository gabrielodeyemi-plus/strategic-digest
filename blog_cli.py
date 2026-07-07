#!/usr/bin/env python3
"""Create a blog artifact from an existing Markdown digest."""

import argparse
from dataclasses import replace
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from blog.config import BlogConfig
from blog.service import BlogPublishingService
from digest_models import Digest


def parse_args():
    parser = argparse.ArgumentParser(
        description="Transform an existing digest into a blog article."
    )
    parser.add_argument("digest_file", type=Path)
    parser.add_argument(
        "--date",
        dest="digest_date",
        type=date.fromisoformat,
        default=date.today(),
        help="Source digest date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Force local draft output; never write to a website repository.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Update an existing artifact for the same digest date.",
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--skip-grounding-review",
        action="store_true",
        help="Run deterministic checks only (useful for development).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    briefing = args.digest_file.read_text(encoding="utf-8")
    config = BlogConfig.from_env()
    config = replace(
        config,
        mode="local" if args.dry_run else config.mode,
        default_status="draft" if args.dry_run else config.default_status,
        existing_post_action="update" if args.force else config.existing_post_action,
        output_dir=args.output_dir or config.output_dir,
        quality_review_enabled=(
            False if args.skip_grounding_review else config.quality_review_enabled
        ),
    )
    digest = Digest.create(briefing, {}, args.digest_date)
    result = BlogPublishingService(config).publish(digest)
    print(result.message)
    if result.artifact_path:
        print(result.artifact_path)


if __name__ == "__main__":
    main()
