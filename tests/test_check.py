import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from blog.approval import approve_blog_post
from blog.check import render_report, run_check
from blog.config import BlogConfig
from blog.publishers import PublishStateStore
from tests.test_approval import DAY, SLUG, TITLE, markdown

# blog:check additionally enforces a minimum article-body word count (an
# approve-time check does not apply this threshold). The shared fixture body
# in tests.test_approval is intentionally short, so pad it here to exercise
# every other check without tripping the word-count gate incidentally.
_FILLER_PARAGRAPH = " ".join(f"substantive{i}" for i in range(60)) + ".\n\n"


def pmarkdown(**kwargs):
    content = markdown(**kwargs)
    return content.replace(
        "Opening analysis remains byte-for-byte unchanged.\n\n",
        "Opening analysis remains byte-for-byte unchanged.\n\n" + _FILLER_PARAGRAPH,
        1,
    )


class CheckTests(unittest.TestCase):
    """Tests for the non-mutating `blog:check` preflight command.

    Fixtures intentionally mirror tests.test_approval so blog:check and
    blog:approve --dry-run are validated against the exact same drafts and
    can never quietly drift apart.
    """

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

    def tearDown(self):
        self.temporary.cleanup()

    def write_post(
        self,
        *,
        filename=f"2026-07-06-{SLUG}.md",
        content=None,
        publish_status="draft",
        quality_status="passed",
        save_state=True,
    ):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        source = self.output_dir / filename
        source.write_text(content or pmarkdown(), encoding="utf-8")
        if save_state:
            metadata = {
                "title": TITLE,
                "slug": SLUG,
                "date": DAY.isoformat(),
                "source_digest_date": DAY.isoformat(),
                "source_digest_id": f"strategic-digest-{DAY.isoformat()}",
                "canonical_url": f"https://gabrielodeyemi.com/blog/{SLUG}",
                "artifact_path": str(source.resolve()),
                "publish_status": publish_status,
                "quality_gate_status": quality_status,
            }
            PublishStateStore(self.output_dir).save(DAY.isoformat(), metadata)
        return source

    def check(self):
        return run_check(DAY, self.config)

    # 1. Fully ready draft returns success.
    def test_fully_ready_draft_returns_success(self):
        self.write_post()
        result = self.check()

        self.assertTrue(result.ready)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.result_label, "READY")
        self.assertEqual(result.blockers, [])
        self.assertEqual(result.title, TITLE)
        self.assertEqual(result.slug, SLUG)
        self.assertGreater(result.word_count, 0)

    # 2. Destination exists produces warning, not failure.
    def test_destination_exists_warns_not_fails(self):
        source = self.write_post()
        destination = self.website_repo / "src" / "content" / "blog" / source.name
        destination.parent.mkdir(parents=True)
        destination.write_text("existing", encoding="utf-8")

        result = self.check()

        self.assertTrue(result.ready)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.result_label, "READY with warnings")
        self.assertTrue(any("--force" in w for w in result.warnings))

    # 3. Missing title fails.
    def test_missing_title_fails(self):
        self.write_post(content=pmarkdown(include_title=False))
        result = self.check()

        self.assertFalse(result.ready)
        self.assertEqual(result.exit_code, 2)
        self.assertTrue(any("title" in b for b in result.blockers))

    # 4. Date mismatch fails.
    def test_date_mismatch_fails(self):
        self.write_post(content=pmarkdown(post_date="2026-07-05"))
        result = self.check()

        self.assertFalse(result.ready)
        self.assertTrue(any("does not match" in b for b in result.blockers))

    # 5. Missing structured sources fails.
    def test_missing_structured_sources_fails(self):
        self.write_post(content=pmarkdown(include_sources=False))
        result = self.check()

        self.assertFalse(result.ready)
        self.assertTrue(
            any("structured frontmatter sources" in b for b in result.blockers)
        )

    # 6. Missing visible Sources section fails.
    def test_missing_visible_sources_section_fails(self):
        self.write_post(content=pmarkdown(body_sources_section=""))
        result = self.check()

        self.assertFalse(result.ready)
        self.assertTrue(
            any('"## Sources" section is missing' in b for b in result.blockers)
        )

    # 7. Insufficient valid source URLs fails.
    def test_insufficient_valid_source_urls_fails(self):
        self.write_post(content=pmarkdown(minimum_sources_required=5))
        result = self.check()

        self.assertFalse(result.ready)
        self.assertTrue(any("coverage below threshold" in b for b in result.blockers))
        self.assertEqual(result.sources_frontmatter_count, 3)
        self.assertEqual(result.sources_required_minimum, 5)

    # 8. Failed quality metadata fails.
    def test_failed_quality_metadata_fails(self):
        self.write_post(publish_status="failed", quality_status="failed")
        result = self.check()

        self.assertFalse(result.ready)
        self.assertTrue(any("quality gate" in b for b in result.blockers))

    # 9. Missing website repo fails.
    def test_missing_website_repo_fails(self):
        self.write_post()
        config = replace(self.config, website_repo_path=self.root / "does-not-exist")
        result = run_check(DAY, config)

        self.assertFalse(result.ready)
        self.assertTrue(
            any("Website repository does not exist" in b for b in result.blockers)
        )

    # 10. Multiple posts for the same date fail.
    def test_multiple_posts_for_date_fails(self):
        self.write_post()
        (self.output_dir / "2026-07-06-another-post.md").write_text(
            pmarkdown(), encoding="utf-8"
        )
        result = self.check()

        self.assertFalse(result.ready)
        self.assertIsNotNone(result.fatal_error)
        self.assertIn("Expected exactly one post", result.fatal_error)
        self.assertEqual(result.exit_code, 2)

    # 11. Already published post returns a clear warning, not a failure,
    # per current approval policy (re-approval is allowed and simply
    # re-copies the file; see approval.py's _VALID_STATE_STATUSES).
    def test_already_published_post_warns(self):
        self.write_post(
            content=pmarkdown(status="published"),
            publish_status="copied_to_website_repo",
        )
        result = self.check()

        self.assertTrue(result.ready)
        self.assertTrue(any('"published"' in w for w in result.warnings))
        self.assertEqual(result.status, "published")

    # Bonus: no draft at all for the date is a clear, non-crashing failure.
    def test_missing_post_fails(self):
        result = self.check()

        self.assertFalse(result.ready)
        self.assertIsNotNone(result.fatal_error)
        self.assertIn("No generated blog post found", result.fatal_error)
        self.assertEqual(result.exit_code, 2)

    # Bonus: render_report never crashes and always surfaces a Result line,
    # for both the happy path and the fatal-error path.
    def test_render_report_includes_result_line(self):
        self.write_post()
        ready_report = render_report(self.check())
        self.assertIn("Result: READY", ready_report)
        self.assertIn("Title:", ready_report)

        blocked_report = render_report(
            run_check(DAY, replace(self.config, output_dir=self.root / "empty"))
        )
        self.assertIn("Result: BLOCKED", blocked_report)

    # Bonus: blog:check and blog:approve --dry-run must never disagree.
    def test_check_agrees_with_approve_dry_run(self):
        self.write_post()
        check_result = self.check()
        approval_result = approve_blog_post(DAY, self.config, dry_run=True)

        self.assertEqual(check_result.ready, approval_result.sources_eligible)
        self.assertEqual(
            check_result.sources_frontmatter_count,
            approval_result.sources_frontmatter_count,
        )
        self.assertEqual(
            check_result.sources_required_minimum,
            approval_result.sources_required_minimum,
        )
        self.assertEqual(check_result.destination_path, approval_result.destination_path)


if __name__ == "__main__":
    unittest.main()
