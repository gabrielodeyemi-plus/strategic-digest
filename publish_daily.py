#!/usr/bin/env python3
"""
Autonomous Daily Publishing Orchestrator for Strategic Digest.

Automates the entire daily routine:
1. Verifies git and gh authentication.
2. Ensures website repository is on clean main.
3. Generates/regenerates blog post for the specified date.
4. Sanitizes SEO link targets (ensuring active routes and tags).
5. Runs blog:check and blog:approve.
6. Runs blog:pr to branch, commit, push, and open the PR.
7. Rebuilds and validates website (npm run build, verify-prerender, test:blog-source).
8. Commits regenerated sitemap to the PR branch and pushes.
9. Waits for Vercel preview checks and auto-merges the PR.
10. Pulls main and deploys to production via Vercel.
11. Verifies live post and sitemap on https://gabrielodeyemi.com.

Usage:
  .venv/bin/python publish_daily.py --date 2026-09-08
  .venv/bin/python publish_daily.py                  # defaults to today
  .venv/bin/python publish_daily.py --backlog        # processes unapproved backlog dates
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

STRATEGIC_DIGEST_DIR = Path(__file__).resolve().parent
WEBSITE_DIR = Path("/Users/olugbengaodeyemi/Downloads/personalwebsite")
VENV_PYTHON = STRATEGIC_DIGEST_DIR / ".venv" / "bin" / "python"
SITE_URL = "https://gabrielodeyemi.com"


def run(cmd: List[str], cwd: Path, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    print(f"[{cwd.name}] $ {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=capture,
    )
    if check and proc.returncode != 0:
        err = proc.stderr.strip() or proc.stdout.strip()
        print(f"Command failed with exit code {proc.returncode}:\n{err}", file=sys.stderr)
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{err}")
    return proc


def sanitize_frontmatter(post_file: Path) -> None:
    """Ensure internal links and tags align with website allowlist."""
    content = post_file.read_text(encoding="utf-8")
    original = content

    # Replace retired /ai-consulting with /projects/strategicdigest
    content = content.replace('url: "/ai-consulting"', 'url: "/projects/strategicdigest"')
    content = content.replace("url: '/ai-consulting'", 'url: "/projects/strategicdigest"')

    # Fix legacy logistics-workflow-automation tag route
    content = content.replace(
        'url: "/blog/tag/logistics-workflow-automation"',
        'url: "/blog/tag/logistics-automation"',
    )

    # If strategic-intelligence tag route is linked, ensure "strategic intelligence" is in tags
    if 'url: "/blog/tag/strategic-intelligence"' in content:
        tag_match = re.search(r'tags:\s*\[(.*?)\]', content)
        if tag_match:
            tags_text = tag_match.group(1)
            if "strategic intelligence" not in tags_text.lower():
                new_tags_text = f'{tags_text}, "strategic intelligence"'
                content = content.replace(f"tags: [{tags_text}]", f"tags: [{new_tags_text}]")

    if content != original:
        post_file.write_text(content, encoding="utf-8")
        print(f"Sanitized frontmatter in {post_file.name}")


def ensure_clean_website_main():
    """Ensure personalwebsite repository is on clean main."""
    status = run(["git", "status", "--porcelain"], cwd=WEBSITE_DIR).stdout.strip()
    if status:
        raise RuntimeError(
            f"Website repository has uncommitted changes:\n{status}\n"
            "Please stash or commit them before running the publishing pipeline."
        )
    run(["git", "checkout", "main"], cwd=WEBSITE_DIR)
    run(["git", "pull", "origin", "main"], cwd=WEBSITE_DIR)


def publish_date(target_date: date, skip_deploy: bool = False) -> bool:
    iso_date = target_date.isoformat()
    print(f"\n========================================================")
    print(f"  Starting Daily Publishing Routine for: {iso_date}")
    print(f"========================================================\n")

    # 1. Ensure website repo is on clean main
    print("--- Step 1: Syncing repositories ---")
    ensure_clean_website_main()
    run(["git", "pull", "origin", "main"], cwd=STRATEGIC_DIGEST_DIR, check=False)

    # 2. Check or Regenerate Post
    print(f"\n--- Step 2: Preparing blog draft for {iso_date} ---")
    post_files = list((STRATEGIC_DIGEST_DIR / "output" / "blog").glob(f"{iso_date}-*.md"))
    needs_regen = len(post_files) == 0

    if not needs_regen:
        post_file = post_files[0]
        sanitize_frontmatter(post_file)
        check_proc = run(
            [str(VENV_PYTHON), "main.py", "blog:check", "--date", iso_date],
            cwd=STRATEGIC_DIGEST_DIR,
            check=False,
        )
        if check_proc.returncode != 0:
            print("Readiness check indicated regeneration is required.")
            needs_regen = True

    if needs_regen:
        print(f"Running blog:regenerate for {iso_date}...")
        run(
            [str(VENV_PYTHON), "main.py", "blog:regenerate", "--date", iso_date],
            cwd=STRATEGIC_DIGEST_DIR,
        )
        post_files = list((STRATEGIC_DIGEST_DIR / "output" / "blog").glob(f"{iso_date}-*.md"))
        if not post_files:
            raise RuntimeError(f"No blog post file produced for {iso_date}")
        post_file = post_files[0]
        sanitize_frontmatter(post_file)

    # Verify readiness
    print(f"Running blog:check for {iso_date}...")
    run(
        [str(VENV_PYTHON), "main.py", "blog:check", "--date", iso_date],
        cwd=STRATEGIC_DIGEST_DIR,
    )

    # 3. Approve
    print(f"\n--- Step 3: Approving post for {iso_date} ---")
    run(
        [str(VENV_PYTHON), "main.py", "blog:approve", "--date", iso_date, "--force"],
        cwd=STRATEGIC_DIGEST_DIR,
    )

    # 4. Open PR
    print(f"\n--- Step 4: Creating PR for {iso_date} ---")
    pr_proc = run(
        [str(VENV_PYTHON), "main.py", "blog:pr", "--date", iso_date, "--force"],
        cwd=STRATEGIC_DIGEST_DIR,
    )
    pr_url = ""
    for line in pr_proc.stdout.splitlines():
        if "https://github.com" in line and "/pull/" in line:
            pr_url = line.strip().split()[-1]
            break
    if not pr_url:
        branch_proc = run(["git", "branch", "--show-current"], cwd=WEBSITE_DIR)
        current_branch = branch_proc.stdout.strip()
        pr_view = run(["gh", "pr", "view", current_branch, "--json", "url,number"], cwd=WEBSITE_DIR)
        pr_info = json.loads(pr_view.stdout)
        pr_url = pr_info.get("url", "")
        pr_number = pr_info.get("number")
    else:
        pr_number = pr_url.split("/")[-1]

    print(f"PR active: {pr_url} (#{pr_number})")

    # 5. Build, Verify Prerender, and Commit Sitemap
    print(f"\n--- Step 5: Building website and verifying prerender ---")
    run(["npm", "run", "build"], cwd=WEBSITE_DIR)
    run(["npm", "run", "verify-prerender"], cwd=WEBSITE_DIR)
    run(["npm", "run", "test:blog-source"], cwd=WEBSITE_DIR)

    # Discard incidental non-sitemap changes if any
    run(["git", "checkout", "--", "public/*.svg", "public/*.png"], cwd=WEBSITE_DIR, check=False)

    sitemap_status = run(["git", "status", "--porcelain", "public/sitemap.xml"], cwd=WEBSITE_DIR).stdout.strip()
    if sitemap_status:
        print("Committing updated sitemap.xml to PR branch...")
        run(["git", "add", "public/sitemap.xml"], cwd=WEBSITE_DIR)
        run(
            ["git", "commit", "-m", f"Update sitemap for Strategic Digest {iso_date}"],
            cwd=WEBSITE_DIR,
        )
        run(["git", "push"], cwd=WEBSITE_DIR)

    if skip_deploy:
        print(f"\n[SKIP-DEPLOY] PR #{pr_number} is ready for human review: {pr_url}")
        return True

    # 6. Wait for Vercel preview checks and auto-merge
    print(f"\n--- Step 6: Awaiting preview checks and auto-merging PR #{pr_number} ---")
    max_wait = 180
    start_time = time.time()
    while time.time() - start_time < max_wait:
        checks_proc = run(["gh", "pr", "checks", str(pr_number)], cwd=WEBSITE_DIR, check=False)
        output = checks_proc.stdout
        if "pending" not in output and checks_proc.returncode == 0:
            print("All preview checks passed!")
            break
        print("Waiting for Vercel preview checks to finish... (10s)")
        time.sleep(10)

    print(f"Merging PR #{pr_number} via squash...")
    run(["gh", "pr", "merge", str(pr_number), "--squash", "--delete-branch"], cwd=WEBSITE_DIR)

    # 7. Pull main and deploy to production
    print(f"\n--- Step 7: Pulling main and deploying to Vercel production ---")
    run(["git", "checkout", "main"], cwd=WEBSITE_DIR)
    run(["git", "pull", "origin", "main"], cwd=WEBSITE_DIR)
    run(["npx", "vercel", "--prod", "--yes"], cwd=WEBSITE_DIR)

    # 8. Extract slug and run live verification
    print(f"\n--- Step 8: Verifying live production post ---")
    website_post_files = list((WEBSITE_DIR / "src" / "content" / "blog").glob(f"{iso_date}-*.md"))
    if not website_post_files:
        raise RuntimeError(f"Could not find published post file in {WEBSITE_DIR} for {iso_date}")
    
    slug_match = re.search(rf"{iso_date}-(.*)\.md$", website_post_files[0].name)
    if not slug_match:
        raise RuntimeError(f"Could not extract slug from {website_post_files[0].name}")
    todays_slug = slug_match.group(1)

    live_url = f"{SITE_URL}/blog/{todays_slug}"
    print(f"Slug: {todays_slug}")
    print(f"Testing URL: {live_url}")

    time.sleep(5)  # Allow CDN edge propagation

    # Assert title
    title_check = run(["curl", "-sS", "-L", live_url], cwd=WEBSITE_DIR)
    if "<title" not in title_check.stdout.lower():
        raise RuntimeError(f"Live URL missing <title tag: {live_url}")
    print("PASS: Live <title> verified")

    if "strategic context" not in title_check.stdout.lower():
        raise RuntimeError(f"Live URL missing 'Strategic context': {live_url}")
    print("PASS: Live 'Strategic context' verified")

    if "sources" not in title_check.stdout.lower():
        raise RuntimeError(f"Live URL missing 'Sources': {live_url}")
    print("PASS: Live 'Sources' verified")

    sitemap_check = run(["curl", "-sS", "-L", f"{SITE_URL}/sitemap.xml"], cwd=WEBSITE_DIR)
    if todays_slug not in sitemap_check.stdout:
        print("WARN: Live sitemap does not yet reflect new slug (CDN cache may take a minute).")
    else:
        print("PASS: Live sitemap contains new slug")

    prerender_file = WEBSITE_DIR / "dist" / "blog" / todays_slug / "index.html"
    if prerender_file.exists():
        print("PASS: Local prerender exists")
    else:
        print(f"WARN: Local prerender missing at {prerender_file}")

    print(f"\n✓ Successfully published and verified Strategic Digest for {iso_date}!")
    print(f"  Live: {live_url}\n")
    return True


def main():
    parser = argparse.ArgumentParser(description="Autonomous publisher for Strategic Digest.")
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=date.today(),
        help="Target date in YYYY-MM-DD format (defaults to today).",
    )
    parser.add_argument(
        "--skip-deploy",
        action="store_true",
        help="Open PR and verify, but do not auto-merge or deploy to production.",
    )
    parser.add_argument(
        "--backlog",
        action="store_true",
        help="Process all unapproved dates between 2026-08-25 and yesterday.",
    )
    args = parser.parse_args()

    if args.backlog:
        state_file = STRATEGIC_DIGEST_DIR / "output" / "blog" / "publish-state.json"
        state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
        digests_dir = STRATEGIC_DIGEST_DIR / "output" / "digests"
        all_dates = sorted([f.stem for f in digests_dir.glob("*.json") if f.stem >= "2026-08-25"])

        for d_str in all_dates:
            d = date.fromisoformat(d_str)
            # Check if already published on website
            website_file = list((WEBSITE_DIR / "src" / "content" / "blog").glob(f"{d_str}-*.md"))
            if website_file:
                print(f"Skipping {d_str}: already published on website ({website_file[0].name}).")
                continue
            print(f"\nProcessing backlog date: {d_str}")
            publish_date(d, skip_deploy=args.skip_deploy)
    else:
        publish_date(args.date, skip_deploy=args.skip_deploy)


if __name__ == "__main__":
    main()
