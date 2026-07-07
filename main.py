#!/usr/bin/env python3
"""
Strategic Intelligence Digest — daily orchestrator.

Run manually:  python main.py
Run via cron:  installed by install.sh as a 7am launchd job
"""

import argparse
import os
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import emailer
import fetcher
import notion_pusher
import synthesizer
from blog import publish_digest_safely
from blog.approval import ApprovalError, approve_blog_post
from blog.check import render_report, run_check
from blog.config import BlogConfig
from blog.pr import PrError, create_pr
from blog.pr import render_report as render_pr_report
from blog.service import BlogPublishingService
from digest_models import Digest


def parse_args():
    parser = argparse.ArgumentParser(description="Run the Strategic Digest agent.")
    parser.add_argument(
        "--digest-only",
        action="store_true",
        help="Generate and save the digest without sending or publishing it.",
    )
    parser.add_argument(
        "--digest-output-dir",
        type=Path,
        default=Path("./output/digests"),
        help="Directory used by --digest-only.",
    )
    commands = parser.add_subparsers(dest="command")
    approval = commands.add_parser(
        "blog:approve",
        help="Approve one reviewed blog draft and copy it to the website repo.",
    )
    approval.add_argument(
        "--date",
        dest="approval_date",
        required=True,
        type=date.fromisoformat,
        help="Digest date in YYYY-MM-DD format.",
    )
    approval.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and show the handoff without modifying files.",
    )
    approval.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing destination file.",
    )

    check = commands.add_parser(
        "blog:check",
        help=(
            "Non-mutating readiness check: is this draft ready to approve "
            "and publish? Never modifies files."
        ),
    )
    check.add_argument(
        "--date",
        dest="check_date",
        required=True,
        type=date.fromisoformat,
        help="Digest date in YYYY-MM-DD format.",
    )

    pr = commands.add_parser(
        "blog:pr",
        help=(
            "Open a GitHub PR for an already-approved, already-copied blog "
            "post. Does not generate or approve content."
        ),
    )
    pr.add_argument(
        "--date",
        dest="pr_date",
        required=True,
        type=date.fromisoformat,
        help="Digest date in YYYY-MM-DD format.",
    )
    pr.add_argument(
        "--dry-run",
        action="store_true",
        help="Report branch name, staged files, build/gh status; no Git state change.",
    )
    pr.add_argument(
        "--force",
        action="store_true",
        help="Proceed despite unrelated dirty changes or an existing branch.",
    )
    pr.add_argument(
        "--branch-name",
        dest="branch_name",
        default=None,
        help="Override the deterministic branch name.",
    )
    pr.add_argument(
        "--base",
        dest="base",
        default=None,
        help="Override the PR base branch (default: BLOG_PR_BASE_BRANCH or main).",
    )
    pr.add_argument(
        "--no-push",
        action="store_true",
        help="Create the local branch and commit, but do not push or open a PR.",
    )
    pr.add_argument(
        "--no-build",
        action="store_true",
        help="Skip `npm run build` in the website repo.",
    )

    regenerate = commands.add_parser(
        "blog:regenerate",
        help=(
            "Re-run the blog transformation for a persisted digest date, "
            "including sources. Always writes a local draft; never touches "
            "the website repo and never approves."
        ),
    )
    regenerate.add_argument(
        "--date",
        dest="regenerate_date",
        required=True,
        type=date.fromisoformat,
        help="Digest date in YYYY-MM-DD format.",
    )
    regenerate.add_argument(
        "--digest-dir",
        type=Path,
        default=Path("./output/digests"),
        help="Directory containing persisted {date}.json digest snapshots.",
    )
    return parser.parse_args()


def deliver(
    digest: Digest,
    notion_push=notion_pusher.push,
    email_send=emailer.send,
    blog_publish=publish_digest_safely,
) -> None:
    """Run independent output adapters without allowing one to stop another."""
    notion_url = ""
    try:
        print("Pushing to Notion...")
        notion_url = notion_push(digest.briefing)
        print(f"  {notion_url}")
    except Exception as e:
        print(f"  Notion push failed: {e}")

    try:
        print("Sending email...")
        email_send(digest.briefing, notion_url)
    except Exception as e:
        print(f"  Email failed: {e}")
        print("  Tip: check GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env")

    try:
        print("Publishing blog article...")
        blog_publish(digest)
    except Exception as e:
        # A custom adapter still cannot break the established delivery path.
        print(f"  Blog publishing failed: {e}")
        print("  Email and Notion delivery are unaffected.")


def main():
    args = parse_args()
    if args.command == "blog:approve":
        return run_blog_approval(args)
    if args.command == "blog:check":
        return run_blog_check(args)
    if args.command == "blog:pr":
        return run_blog_pr(args)
    if args.command == "blog:regenerate":
        return run_blog_regenerate(args)

    print("── Strategic Intelligence Digest ─────────────────────")

    # 1. Load topics
    topics_path = Path(__file__).parent / "topics.yaml"
    print(f"Loading topics from {topics_path.name}...")
    topics = fetcher.load_topics(str(topics_path))
    print(f"  {len(topics)} topics configured")

    # 2. Fetch articles
    print("Fetching articles...")
    articles_by_topic = fetcher.fetch_all(topics)
    total = sum(len(v) for v in articles_by_topic.values())
    print(f"  {total} articles fetched")
    for topic, arts in articles_by_topic.items():
        print(f"    {topic}: {len(arts)} articles")

    if total == 0:
        print("No articles found. Check your RSS feeds.")
        sys.exit(0)

    # 3. Synthesize with Claude
    print("Synthesizing with Claude...")
    briefing = synthesizer.synthesize(articles_by_topic)
    print(f"  Briefing generated ({len(briefing.split())} words)")

    digest = Digest.create(
        briefing=briefing,
        articles_by_topic=articles_by_topic,
        digest_date=date.today(),
    )

    # Persist the full digest, including source URLs, so it survives after
    # the originating RSS items age out of their 48-hour feed window. This is
    # what `blog:regenerate` reloads to rebuild a sourced draft later.
    try:
        digest_snapshot_path = digest.save(args.digest_output_dir)
        print(f"  Digest snapshot saved to {digest_snapshot_path.resolve()}")
    except Exception as e:
        print(f"  Digest snapshot could not be saved: {e}")

    if args.digest_only:
        args.digest_output_dir.mkdir(parents=True, exist_ok=True)
        path = args.digest_output_dir / f"{digest.digest_date.isoformat()}.md"
        path.write_text(digest.briefing.rstrip() + "\n", encoding="utf-8")
        print(f"  Digest saved to {path.resolve()}")
        print("── Done (digest only) ─────────────────────────────────")
        return 0

    # 4-6. Preserve existing Notion/email delivery, then add the blog path.
    deliver(digest)

    print("── Done ───────────────────────────────────────────────")
    return 0


def run_blog_approval(args) -> int:
    try:
        config = BlogConfig.from_env()
        result = approve_blog_post(
            args.approval_date,
            config,
            dry_run=args.dry_run,
            force=args.force,
        )
    except (ApprovalError, ValueError, OSError) as exc:
        print(f"Blog approval failed: {exc}", file=sys.stderr)
        return 2

    if result.dry_run:
        print("── Blog approval dry run ──────────────────────────────")
        print(f"Title:        {result.title}")
        print(f"Slug:         {result.slug}")
        print(f"Date:         {result.requested_date.isoformat()}")
        print(f"Status:       {result.current_status}")
        print(f"Source:       {result.source_path}")
        print(f"Destination:  {result.destination_path}")
        print(
            "Exists:       "
            + ("yes (use --force to overwrite)" if result.destination_exists else "no")
        )
        print("")
        print("Sources:")
        print(f"- Frontmatter sources: {result.sources_frontmatter_count} valid")
        print(
            "- Visible Sources section: "
            + ("yes" if result.sources_visible_present else "no")
        )
        print(
            "- Source coverage: "
            + ("PASS" if result.sources_coverage_pass else "FAIL")
            + f" ({result.sources_frontmatter_count} valid, "
            f"{result.sources_required_minimum} expected)"
        )
        print(
            "- Approval eligible: " + ("yes" if result.sources_eligible else "no")
        )
        print("")
        print("No files were modified.")
        return 0

    print("── Blog post approved ─────────────────────────────────")
    print(f"Title:       {result.title}")
    print(f"Status:      published")
    print(f"Source:      {result.source_path}")
    print(f"Copied to:   {result.destination_path}")
    print(f"Overwrite:   {'yes' if result.overwritten else 'no'}")
    print("")
    print("Next steps:")
    print(f"1. cd {config.website_repo_path.expanduser().resolve()}")
    print("2. npm run build")
    print("3. git diff")
    print(f"4. git add {config.website_content_dir}/{result.destination_path.name}")
    print(
        '5. git commit -m "Publish Strategic Digest: '
        f'{result.requested_date.isoformat()}"'
    )
    print("6. git push")
    print("")
    print("No commit, push, or Vercel deployment was performed.")
    return 0


def run_blog_check(args) -> int:
    """Report whether a draft is ready to approve, without touching files."""
    try:
        config = BlogConfig.from_env()
    except ValueError as exc:
        print(f"Blog check failed: {exc}", file=sys.stderr)
        return 2

    result = run_check(args.check_date, config)
    print(render_report(result))
    return result.exit_code


def run_blog_pr(args) -> int:
    """Open a GitHub PR for an already-approved, already-copied post."""
    try:
        config = BlogConfig.from_env()
    except ValueError as exc:
        print(f"Blog PR failed: {exc}", file=sys.stderr)
        return 2

    try:
        result = create_pr(
            args.pr_date,
            config,
            dry_run=args.dry_run,
            force=args.force,
            branch_name=args.branch_name,
            base=args.base,
            no_push=args.no_push,
            no_build=args.no_build,
        )
    except PrError as exc:
        print(f"Blog PR failed: {exc}", file=sys.stderr)
        return 2

    print(render_pr_report(result))
    return 0


def run_blog_regenerate(args) -> int:
    """Re-run the blog transformation for a persisted digest, with sources.

    This is the repair/regenerate path referenced in Step 6: it reloads the
    saved {date}.json digest snapshot (which carries the original source
    metadata), reruns BlogArticleTransformer + BlogQualityGate, and always
    writes a local draft. It never writes to the website repo, and never
    approves or publishes.
    """
    digest_path = args.digest_dir / f"{args.regenerate_date.isoformat()}.json"
    if not digest_path.exists():
        print(
            f"Blog regeneration failed: no persisted digest snapshot found at "
            f"{digest_path.resolve()}. Snapshots are written automatically by "
            "the daily run (or --digest-only) going forward; older dates "
            "predating this feature cannot be regenerated this way.",
            file=sys.stderr,
        )
        return 2

    try:
        digest = Digest.load(digest_path)
    except Exception as exc:
        print(f"Blog regeneration failed: could not read {digest_path}: {exc}", file=sys.stderr)
        return 2

    try:
        config = BlogConfig.from_env()
    except ValueError as exc:
        print(f"Blog regeneration failed: {exc}", file=sys.stderr)
        return 2

    config = replace(
        config,
        mode="local",
        default_status="draft",
        existing_post_action="update",
    )

    try:
        result = BlogPublishingService(config).publish(digest)
    except Exception as exc:
        print(f"Blog regeneration failed: {exc}", file=sys.stderr)
        return 2

    print("── Blog draft regenerated ─────────────────────────────")
    print(f"Digest date:  {digest.digest_date.isoformat()}")
    print(f"Status:       {result.status}")
    print(f"Artifact:     {result.artifact_path}")
    print(result.message)
    print("")
    print("Website repo was not touched. Nothing was approved or deployed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
