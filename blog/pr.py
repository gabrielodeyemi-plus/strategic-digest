"""GitHub PR publishing workflow for an already-approved blog post.

`blog:pr` automates the boring Git/GitHub mechanics (branch, commit, push,
PR) for a post that a human has already reviewed and approved with
`blog:approve`. It never generates or approves content, and it never runs a
production deploy -- it only opens a pull request so Gabriel can review the
Vercel preview and merge manually.

Safety model:
- Every structural check below (post exists, is approved, was copied to the
  website repo, the website repo is clean apart from that one file, the
  target branch does not already exist) is enforced in *both* dry-run and
  real runs, mirroring how `blog:approve --dry-run` still raises on
  structural problems. This means a successful dry run is a reliable signal
  that the real run will also succeed structurally.
- Only side-effecting steps (gh availability/auth enforcement, the actual
  `npm run build`, branch creation, staging, commit, push, and PR creation)
  are skipped during a dry run. Dry run still *reports* gh availability and
  whether a build would run, without executing or blocking on either.
- All subprocess calls go through an injectable `runner` so tests can
  substitute deterministic fakes instead of touching real Git, npm, or gh.
"""

import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, List, Optional

import yaml

from blog.approval import (
    ApprovalError,
    _FRONTMATTER,
    _evaluate_sources_readiness,
    _resolve_slug,
    _resolve_website_paths,
)
from blog.approval import _locate_source as _locate_generated_source
from blog.config import BlogConfig
from blog.publishers import PublishStateStore

Runner = Callable[..., subprocess.CompletedProcess]


class PrError(RuntimeError):
    """A safe, user-actionable failure in the PR publishing workflow."""


@dataclass(frozen=True)
class PrResult:
    requested_date: date
    dry_run: bool
    title: str
    slug: str
    source_path: Path
    website_path: Path
    branch_name: str
    base_branch: str
    files_staged: List[str] = field(default_factory=list)
    branch_exists: bool = False
    gh_available: bool = False
    gh_authenticated: bool = False
    build_will_run: bool = False
    build_ran: bool = False
    build_passed: Optional[bool] = None
    committed: bool = False
    commit_message: str = ""
    pushed: bool = False
    pr_created: bool = False
    pr_url: str = ""
    pr_title: str = ""
    pr_body: str = ""


def _default_runner(cmd: List[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )


def _run(
    cmd: List[str], cwd: Optional[Path], runner: Runner
) -> subprocess.CompletedProcess:
    try:
        return runner(cmd, cwd=cwd)
    except FileNotFoundError:
        return subprocess.CompletedProcess(
            args=cmd, returncode=127, stdout="", stderr=f"{cmd[0]}: command not found"
        )


def _parse_dirty_paths(porcelain_output: str) -> List[str]:
    """Extract the changed paths from `git status --porcelain` output."""
    paths = []
    for raw in porcelain_output.splitlines():
        if not raw.strip() or len(raw) <= 3:
            continue
        rest = raw[3:]
        if " -> " in rest:
            rest = rest.split(" -> ", 1)[1]
        paths.append(rest.strip().strip('"'))
    return paths


def _branch_exists(repo_path: Path, branch: str, runner: Runner) -> bool:
    result = _run(
        ["git", "rev-parse", "--verify", "--quiet", branch], repo_path, runner
    )
    return result.returncode == 0


def _build_pr_body(
    *,
    title: str,
    requested_date: date,
    slug: str,
    source_path: Path,
    website_path: Path,
    sources_readiness: dict,
    build_will_run: bool,
    build_passed: Optional[bool],
) -> str:
    if not build_will_run:
        build_line = "Skipped (--no-build)"
    elif build_passed is None:
        build_line = "Not run yet (dry run)"
    else:
        build_line = "Passed" if build_passed else "Failed"

    return "\n".join(
        [
            f"**Post:** {title}",
            f"**Date:** {requested_date.isoformat()}",
            f"**Slug:** {slug}",
            f"**Local file:** `{source_path}`",
            f"**Website path:** `{website_path}`",
            "",
            "**Source readiness:** "
            + (
                "PASS"
                if sources_readiness["coverage_pass"]
                else "FAIL"
            )
            + f" ({sources_readiness['frontmatter_count']} valid, "
            f"{sources_readiness['required_minimum']} expected)",
            f"**Build result:** {build_line}",
            "",
            "**Checklist:**",
            "- [ ] Review article body",
            "- [ ] Verify Sources section",
            "- [ ] Verify /blog index in Vercel preview",
            f"- [ ] Verify /blog/{slug} in Vercel preview",
            "- [ ] Merge after Vercel preview passes",
        ]
    )


def create_pr(
    requested_date: date,
    config: BlogConfig,
    *,
    dry_run: bool = False,
    force: bool = False,
    branch_name: Optional[str] = None,
    base: Optional[str] = None,
    no_push: bool = False,
    no_build: bool = False,
    runner: Runner = _default_runner,
) -> PrResult:
    """Open a GitHub PR for an already-approved, already-copied blog post.

    This never generates or approves content. It only operates on a post
    that `blog:approve` has already copied into the website repo.
    """
    if not config.pr_enabled:
        raise PrError(
            "The blog:pr workflow is disabled. Set BLOG_PR_ENABLED=true to enable it."
        )

    # 1. Locate the generated post and confirm it is approved/published.
    try:
        source_path = _locate_generated_source(config.output_dir, requested_date)
    except ApprovalError as exc:
        raise PrError(str(exc)) from exc

    markdown = source_path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(markdown)
    if not match:
        raise PrError(f"{source_path.name} has no valid YAML frontmatter.")
    try:
        frontmatter = yaml.safe_load(match.group("yaml"))
    except yaml.YAMLError as exc:
        raise PrError(f"{source_path.name} has invalid YAML frontmatter: {exc}") from exc
    if not isinstance(frontmatter, dict):
        raise PrError(f"{source_path.name} frontmatter must be an object.")

    title = str(frontmatter.get("title") or "").strip()
    status = str(frontmatter.get("status") or "").strip().lower()
    if status != "published":
        raise PrError(
            f'{source_path.name} status is "{status or "missing"}", not '
            '"published". Run blog:approve before blog:pr.'
        )

    try:
        slug = _resolve_slug(frontmatter, source_path, requested_date)
    except ApprovalError as exc:
        raise PrError(str(exc)) from exc

    # 2. Confirm approval metadata shows the post was copied to the website repo.
    metadata = PublishStateStore(config.output_dir).get(requested_date.isoformat())
    state_status = str(
        (metadata or {}).get("publish_status") or (metadata or {}).get("status") or ""
    ).lower()
    if not metadata or state_status != "copied_to_website_repo":
        raise PrError(
            "Approval metadata does not show this post was copied to the "
            "website repo. Run blog:approve before blog:pr."
        )

    # 3/4/5. Resolve and validate the website repo/content paths.
    try:
        repo_path, _destination_dir, website_path = _resolve_website_paths(
            config, source_path
        )
    except ApprovalError as exc:
        raise PrError(str(exc)) from exc

    if not website_path.exists():
        raise PrError(
            f"Approved file not found in the website repo: {website_path}. "
            "Run blog:approve again."
        )

    # 6. Dirty-tree policy: only the approved post's own change is allowed.
    relative_path = str(website_path.relative_to(repo_path))
    status_result = _run(["git", "status", "--porcelain"], repo_path, runner)
    if status_result.returncode != 0:
        raise PrError(
            f"Could not read Git status for {repo_path}: {status_result.stderr.strip()}"
        )
    dirty_paths = _parse_dirty_paths(status_result.stdout)
    unexpected = [path for path in dirty_paths if path != relative_path]
    if unexpected and not force:
        listing = "\n".join(f"  - {path}" for path in unexpected)
        raise PrError(
            "The website repo has unrelated dirty changes. Commit or stash "
            f"them, or rerun with --force:\n{listing}"
        )
    if relative_path not in dirty_paths and not force:
        raise PrError(
            f"No pending Git changes found for {relative_path} in the website "
            "repo. It may already be committed, or blog:approve may not have "
            "run against this repo."
        )

    files_staged = [relative_path]

    # Branch naming and collision check (always computed, only enforced for real runs).
    base_branch = base or config.pr_base_branch
    default_branch = f"{config.pr_branch_prefix}/{requested_date.isoformat()}-{slug}"
    chosen_branch = branch_name or default_branch
    branch_already_exists = _branch_exists(repo_path, chosen_branch, runner)
    if branch_already_exists and not force:
        raise PrError(
            f'Branch "{chosen_branch}" already exists. Use --force to proceed anyway.'
        )

    # gh availability/auth: always checked and reported; only enforced on real runs.
    version_result = _run(["gh", "--version"], repo_path, runner)
    gh_available = version_result.returncode == 0
    gh_authenticated = False
    if gh_available:
        auth_result = _run(["gh", "auth", "status"], repo_path, runner)
        gh_authenticated = auth_result.returncode == 0

    sources_readiness = _evaluate_sources_readiness(frontmatter, markdown)
    build_will_run = config.pr_run_build and not no_build

    if dry_run:
        return PrResult(
            requested_date=requested_date,
            dry_run=True,
            title=title,
            slug=slug,
            source_path=source_path.resolve(),
            website_path=website_path,
            branch_name=chosen_branch,
            base_branch=base_branch,
            files_staged=files_staged,
            branch_exists=branch_already_exists,
            gh_available=gh_available,
            gh_authenticated=gh_authenticated,
            build_will_run=build_will_run,
            pr_title=f"Publish Strategic Digest: {title or requested_date.isoformat()}",
            pr_body=_build_pr_body(
                title=title,
                requested_date=requested_date,
                slug=slug,
                source_path=source_path.resolve(),
                website_path=website_path,
                sources_readiness=sources_readiness,
                build_will_run=build_will_run,
                build_passed=None,
            ),
        )

    # From here on we actually mutate Git state, so gh must be ready first.
    if not gh_available:
        raise PrError(
            "GitHub CLI (gh) is not installed. Install it "
            "(https://cli.github.com), then run `gh auth login`, and rerun "
            "this command."
        )
    if not gh_authenticated:
        raise PrError(
            "GitHub CLI (gh) is not authenticated. Run `gh auth login`, then "
            "rerun this command."
        )

    build_ran = False
    build_passed: Optional[bool] = None
    if build_will_run:
        build_result = _run(["npm", "run", "build"], repo_path, runner)
        build_ran = True
        build_passed = build_result.returncode == 0
        if not build_passed:
            raise PrError(
                "Website build failed (npm run build). Aborting before any "
                f"branch, commit, or push.\n{build_result.stdout}\n{build_result.stderr}"
            )

    # 8. Create the branch.
    checkout_result = _run(
        ["git", "checkout", "-b", chosen_branch], repo_path, runner
    )
    if checkout_result.returncode != 0:
        raise PrError(
            f"Could not create branch {chosen_branch}: {checkout_result.stderr.strip()}"
        )

    # 9/10. Stage only the relevant blog post file.
    add_result = _run(["git", "add", "--", relative_path], repo_path, runner)
    if add_result.returncode != 0:
        raise PrError(f"Could not stage {relative_path}: {add_result.stderr.strip()}")

    # 11. Commit.
    commit_message = f"Publish Strategic Digest: {requested_date.isoformat()}"
    commit_result = _run(
        ["git", "commit", "-m", commit_message], repo_path, runner
    )
    if commit_result.returncode != 0:
        raise PrError(f"Commit failed: {commit_result.stderr.strip()}")

    pushed = False
    pr_created = False
    pr_url = ""
    pr_title = f"Publish Strategic Digest: {title or requested_date.isoformat()}"
    pr_body = _build_pr_body(
        title=title,
        requested_date=requested_date,
        slug=slug,
        source_path=source_path.resolve(),
        website_path=website_path,
        sources_readiness=sources_readiness,
        build_will_run=build_will_run,
        build_passed=build_passed,
    )

    if not no_push:
        # 12. Push.
        push_result = _run(
            ["git", "push", "-u", "origin", chosen_branch], repo_path, runner
        )
        if push_result.returncode != 0:
            raise PrError(f"Push failed: {push_result.stderr.strip()}")
        pushed = True

        # 13. Open the PR.
        pr_result = _run(
            [
                "gh",
                "pr",
                "create",
                "--base",
                base_branch,
                "--head",
                chosen_branch,
                "--title",
                pr_title,
                "--body",
                pr_body,
            ],
            repo_path,
            runner,
        )
        if pr_result.returncode != 0:
            raise PrError(f"PR creation failed: {pr_result.stderr.strip()}")
        pr_created = True
        lines = [line.strip() for line in pr_result.stdout.splitlines() if line.strip()]
        pr_url = lines[-1] if lines else ""

    return PrResult(
        requested_date=requested_date,
        dry_run=False,
        title=title,
        slug=slug,
        source_path=source_path.resolve(),
        website_path=website_path,
        branch_name=chosen_branch,
        base_branch=base_branch,
        files_staged=files_staged,
        branch_exists=branch_already_exists,
        gh_available=gh_available,
        gh_authenticated=gh_authenticated,
        build_will_run=build_will_run,
        build_ran=build_ran,
        build_passed=build_passed,
        committed=True,
        commit_message=commit_message,
        pushed=pushed,
        pr_created=pr_created,
        pr_url=pr_url,
        pr_title=pr_title,
        pr_body=pr_body,
    )


def render_report(result: PrResult) -> str:
    lines = ["── Blog PR ────────────────────────────────────────────"]
    lines.append(f"Title:        {result.title}")
    lines.append(f"Slug:         {result.slug}")
    lines.append(f"Date:         {result.requested_date.isoformat()}")
    lines.append(f"Branch:       {result.branch_name}"
                 + (" (already exists)" if result.branch_exists else ""))
    lines.append(f"Base branch:  {result.base_branch}")
    lines.append(f"Files staged: {', '.join(result.files_staged) or '(none)'}")
    lines.append(
        "gh CLI:       "
        + ("available" if result.gh_available else "NOT INSTALLED")
        + ", "
        + ("authenticated" if result.gh_authenticated else "NOT AUTHENTICATED")
    )
    if result.build_will_run:
        if result.dry_run:
            build_line = "would run (npm run build)"
        elif result.build_passed is None:
            build_line = "did not run"
        else:
            build_line = "passed" if result.build_passed else "FAILED"
    else:
        build_line = "skipped (--no-build)"
    lines.append(f"Build:        {build_line}")
    lines.append("")

    if result.dry_run:
        lines.append("Dry run: no Git state was modified, nothing was committed,")
        lines.append("pushed, or opened as a pull request.")
        return "\n".join(lines)

    lines.append(f"Committed:    {'yes — ' + result.commit_message if result.committed else 'no'}")
    lines.append(f"Pushed:       {'yes' if result.pushed else 'no'}")
    if result.pr_created:
        lines.append(f"Pull request: {result.pr_url}")
    else:
        lines.append("Pull request: not opened (--no-push)")
    return "\n".join(lines)
