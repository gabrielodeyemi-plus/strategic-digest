import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from blog.config import BlogConfig
from blog.pr import PrError, create_pr
from blog.publishers import PublishStateStore
from tests.test_approval import DAY, SLUG, TITLE, markdown


def _cp(cmd, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=cmd, returncode=returncode, stdout=stdout, stderr=stderr
    )


class FakeRunner:
    """Deterministic stand-in for subprocess.run, keyed by argv[0:2].

    No test in this module touches a real Git repo, npm, or gh -- every
    subprocess boundary is intercepted here, per the safety rule that this
    suite must never create a real PR or push to a real remote.
    """

    def __init__(self, overrides=None):
        self.calls = []
        self.overrides = overrides or {}

    def __call__(self, cmd, cwd=None):
        self.calls.append((tuple(cmd), cwd))
        key = tuple(cmd[:2])
        if key in self.overrides:
            response = self.overrides[key]
            return response(cmd, cwd) if callable(response) else response
        defaults = {
            ("git", "status"): _cp(cmd, 0, stdout=""),
            ("git", "rev-parse"): _cp(cmd, 1),
            ("git", "checkout"): _cp(cmd, 0),
            ("git", "add"): _cp(cmd, 0),
            ("git", "commit"): _cp(cmd, 0),
            ("git", "push"): _cp(cmd, 0),
            ("gh", "--version"): _cp(cmd, 0, stdout="gh version 2.50.0"),
            ("gh", "auth"): _cp(cmd, 0, stdout="Logged in to github.com"),
            ("gh", "pr"): _cp(
                cmd,
                0,
                stdout="https://github.com/gabrielodeyemi-plus/personalwebsite/pull/42\n",
            ),
            ("npm", "run"): _cp(cmd, 0),
        }
        return defaults.get(key, _cp(cmd, 0))

    def called(self, *prefix):
        return any(cmd[: len(prefix)] == tuple(prefix) for cmd, _ in self.calls)


class PrTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output_dir = self.root / "output" / "blog"
        self.website_repo = self.root / "website"
        (self.website_repo / ".git").mkdir(parents=True)
        self.config = replace(
            BlogConfig(),
            output_dir=self.output_dir,
            website_repo_path=self.website_repo,
            website_content_dir="src/content/blog",
        )
        self.filename = f"2026-07-06-{SLUG}.md"
        self.relative_path = f"src/content/blog/{self.filename}"

    def tearDown(self):
        self.temporary.cleanup()

    def write_approved_post(
        self,
        *,
        publish_status="copied_to_website_repo",
        copy_to_website=True,
        status="published",
    ):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        content = markdown(status=status)
        source = self.output_dir / self.filename
        source.write_text(content, encoding="utf-8")

        destination_dir = self.website_repo / "src" / "content" / "blog"
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / self.filename
        if copy_to_website:
            destination.write_text(content, encoding="utf-8")

        metadata = {
            "title": TITLE,
            "slug": SLUG,
            "date": DAY.isoformat(),
            "artifact_path": str(source.resolve()),
            "publish_status": publish_status,
            "status": publish_status,
            "website_content_path": str(destination.resolve()),
            "quality_gate_status": "passed",
        }
        PublishStateStore(self.output_dir).save(DAY.isoformat(), metadata)
        return source, destination

    def default_runner(self, overrides=None):
        merged = {
            ("git", "status"): _cp(
                ["git", "status"], 0, stdout=f" M {self.relative_path}\n"
            )
        }
        merged.update(overrides or {})
        return FakeRunner(merged)

    def run_pr(self, runner=None, **kwargs):
        return create_pr(
            DAY, self.config, runner=(runner or self.default_runner()), **kwargs
        )

    # 1. PR dry run succeeds for approved, copied post.
    def test_dry_run_succeeds_for_approved_copied_post(self):
        self.write_approved_post()
        result = self.run_pr(dry_run=True)

        self.assertTrue(result.dry_run)
        self.assertEqual(
            result.branch_name, f"strategic-digest/{DAY.isoformat()}-{SLUG}"
        )
        self.assertEqual(result.files_staged, [self.relative_path])
        self.assertTrue(result.gh_available)
        self.assertTrue(result.gh_authenticated)
        self.assertTrue(result.build_will_run)
        self.assertFalse(result.committed)
        self.assertFalse(result.pushed)
        self.assertFalse(result.pr_created)

    # 2. PR command refuses an unapproved draft.
    def test_refuses_unapproved_draft(self):
        self.write_approved_post(publish_status="draft", status="draft")
        with self.assertRaisesRegex(PrError, r'not "published"'):
            self.run_pr(dry_run=True)

    def test_refuses_duplicate_frontmatter_keys_in_website_copy(self):
        _source, destination = self.write_approved_post()
        corrupted = destination.read_text(encoding="utf-8").replace(
            f'slug: "{SLUG}"\n',
            f'slug: "{SLUG}"\nstatus: "draft"\n',
            1,
        )
        destination.write_text(corrupted, encoding="utf-8")

        with self.assertRaisesRegex(PrError, "Duplicate frontmatter key: status"):
            self.run_pr(dry_run=True)

    # 3. PR command refuses a missing copied website file.
    def test_refuses_missing_copied_website_file(self):
        self.write_approved_post(copy_to_website=False)
        with self.assertRaisesRegex(PrError, "Approved file not found"):
            self.run_pr(dry_run=True)

    # 4. PR command refuses dirty unrelated website changes.
    def test_refuses_dirty_unrelated_changes(self):
        self.write_approved_post()
        runner = self.default_runner(
            {
                ("git", "status"): _cp(
                    ["git", "status"],
                    0,
                    stdout=f" M {self.relative_path}\n M src/App.tsx\n",
                )
            }
        )
        with self.assertRaisesRegex(PrError, "unrelated dirty changes"):
            self.run_pr(runner=runner, dry_run=True)

    # 5. PR command accepts only the expected blog post change.
    def test_accepts_only_expected_change(self):
        self.write_approved_post()
        result = self.run_pr(dry_run=True)
        self.assertEqual(result.files_staged, [self.relative_path])

    # 6. PR command fails clearly when gh is missing.
    def test_fails_when_gh_missing(self):
        self.write_approved_post()
        runner = self.default_runner(
            {("gh", "--version"): _cp(["gh", "--version"], 127, stderr="not found")}
        )
        with self.assertRaisesRegex(PrError, "not installed"):
            self.run_pr(runner=runner)

    # 7. PR command fails clearly when gh is unauthenticated.
    def test_fails_when_gh_unauthenticated(self):
        self.write_approved_post()
        runner = self.default_runner(
            {
                ("gh", "auth"): _cp(
                    ["gh", "auth", "status"], 1, stderr="not logged in"
                )
            }
        )
        with self.assertRaisesRegex(PrError, "not authenticated"):
            self.run_pr(runner=runner)

    # 8. Branch naming is deterministic.
    def test_branch_naming_is_deterministic(self):
        self.write_approved_post()
        result_a = self.run_pr(dry_run=True)
        result_b = self.run_pr(dry_run=True)

        self.assertEqual(result_a.branch_name, result_b.branch_name)
        self.assertEqual(result_a.branch_name, f"strategic-digest/2026-07-06-{SLUG}")

    # 9. Build failure blocks PR creation.
    def test_build_failure_blocks_pr_creation(self):
        self.write_approved_post()
        runner = self.default_runner(
            {("npm", "run"): _cp(["npm", "run", "build"], 1, stderr="build broke")}
        )
        with self.assertRaisesRegex(PrError, "build failed"):
            self.run_pr(runner=runner)

        self.assertFalse(runner.called("git", "checkout"))
        self.assertFalse(runner.called("git", "commit"))
        self.assertFalse(runner.called("gh", "pr"))

    # 10. --no-build skips build.
    def test_no_build_skips_build(self):
        self.write_approved_post()
        runner = self.default_runner()
        result = self.run_pr(runner=runner, no_build=True)

        self.assertFalse(runner.called("npm", "run"))
        self.assertFalse(result.build_will_run)
        self.assertTrue(result.pr_created)

    # 11. --no-push creates local branch/commit but does not push or open PR.
    def test_no_push_stops_before_push(self):
        self.write_approved_post()
        runner = self.default_runner()
        result = self.run_pr(runner=runner, no_push=True)

        self.assertTrue(result.committed)
        self.assertFalse(result.pushed)
        self.assertFalse(result.pr_created)
        self.assertFalse(runner.called("git", "push"))
        self.assertFalse(runner.called("gh", "pr"))

    # Bonus: a full real run creates the branch, commits, pushes, and opens a PR.
    def test_real_run_creates_branch_commits_pushes_and_opens_pr(self):
        self.write_approved_post()
        runner = self.default_runner()
        result = self.run_pr(runner=runner)

        self.assertTrue(result.committed)
        self.assertTrue(result.pushed)
        self.assertTrue(result.pr_created)
        self.assertTrue(result.pr_url.startswith("https://"))
        self.assertTrue(runner.called("git", "checkout"))
        self.assertTrue(runner.called("git", "add"))
        self.assertTrue(runner.called("git", "commit"))
        self.assertTrue(runner.called("git", "push"))
        self.assertTrue(runner.called("gh", "pr"))

    # Bonus: an existing branch blocks unless --force is passed.
    def test_existing_branch_blocks_without_force(self):
        self.write_approved_post()
        runner = self.default_runner(
            {("git", "rev-parse"): _cp(["git", "rev-parse"], 0)}
        )
        with self.assertRaisesRegex(PrError, "already exists"):
            self.run_pr(runner=runner, dry_run=True)

    def test_existing_branch_allowed_with_force(self):
        self.write_approved_post()
        runner = self.default_runner(
            {("git", "rev-parse"): _cp(["git", "rev-parse"], 0)}
        )
        result = self.run_pr(runner=runner, dry_run=True, force=True)
        self.assertTrue(result.branch_exists)


if __name__ == "__main__":
    unittest.main()
