import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from blog.approval import ApprovalError, approve_blog_post
from blog.config import BlogConfig
from blog.publishers import PublishStateStore


DAY = date(2026, 7, 6)
TITLE = "The Trust Gate: Control Is the New AI Constraint"
SLUG = "trust-gate-control-ai-constraint"

_VALID_SOURCES_YAML = (
    "sources:\n"
    '  - title: "Alibaba reportedly bans employees from using Claude Code"\n'
    '    url: "https://techcrunch.com/2026/07/04/alibaba-reportedly-bans-employees-from-using-claude-code/"\n'
    '    publisher: "TechCrunch"\n'
    '    date: "2026-07-04"\n'
    '  - title: "Amazon will stop accepting new customers for Mechanical Turk"\n'
    '    url: "https://techcrunch.com/2026/07/05/amazon-will-stop-accepting-new-customers-for-mechanical-turk/"\n'
    '    publisher: "TechCrunch"\n'
    '    date: "2026-07-05"\n'
    '  - title: "Some of the nation\'s rich are letting AI teach their kids"\n'
    '    url: "https://www.theverge.com/ai-artificial-intelligence/961505/wealthy-ai-schools-alpha-forge-prep"\n'
    '    publisher: "The Verge"\n'
    '    date: "2026-07-05"\n'
)
_VALID_SOURCES_SECTION = (
    "## Sources\n\n"
    "- [Alibaba reportedly bans employees from using Claude Code]"
    "(https://techcrunch.com/2026/07/04/alibaba-reportedly-bans-employees-from-using-claude-code/), "
    "TechCrunch, 2026-07-04\n"
    "- [Amazon will stop accepting new customers for Mechanical Turk]"
    "(https://techcrunch.com/2026/07/05/amazon-will-stop-accepting-new-customers-for-mechanical-turk/), "
    "TechCrunch, 2026-07-05\n"
    "- [Some of the nation's rich are letting AI teach their kids]"
    "(https://www.theverge.com/ai-artificial-intelligence/961505/wealthy-ai-schools-alpha-forge-prep), "
    "The Verge, 2026-07-05\n"
)


def markdown(
    post_date="2026-07-06",
    status="draft",
    include_title=True,
    include_sources=True,
    minimum_sources_required=3,
    body_sources_section=None,
):
    title_line = f'title: "{TITLE}"\n' if include_title else ""
    sources_yaml = _VALID_SOURCES_YAML if include_sources else "sources: []\n"
    if body_sources_section is None:
        body_sources_section = _VALID_SOURCES_SECTION if include_sources else ""
    return (
        "---\n"
        f"{title_line}"
        f'date: "{post_date}"\n'
        'author: "Gabriel Odeyemi"\n'
        f'slug: "{SLUG}"\n'
        'tags: ["strategy", "AI"]\n'
        f'status: "{status}"\n'
        'excerpt: "A precise strategic reading."\n'
        f"minimum_sources_required: {minimum_sources_required}\n"
        f"{sources_yaml}"
        "---\n\n"
        "Opening analysis remains byte-for-byte unchanged.\n\n"
        "## The Strategic Read\n\n"
        "The implication is clear.\n"
        + (f"\n{body_sources_section}" if body_sources_section else "")
    )


class ApprovalTests(unittest.TestCase):
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
    ):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        source = self.output_dir / filename
        source.write_text(content or markdown(), encoding="utf-8")
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

    def approve(self, **kwargs):
        return approve_blog_post(
            DAY,
            self.config,
            now=datetime(2026, 7, 6, 19, 0, tzinfo=timezone.utc),
            **kwargs,
        )

    def test_approving_draft_copies_it_to_website_content(self):
        source = self.write_post()
        result = self.approve()

        self.assertTrue(result.destination_path.exists())
        self.assertEqual(
            result.destination_path.read_text(encoding="utf-8"),
            source.read_text(encoding="utf-8"),
        )
        metadata = PublishStateStore(self.output_dir).get(DAY.isoformat())
        self.assertEqual(metadata["status"], "copied_to_website_repo")
        self.assertEqual(metadata["approved_file_path"], str(source.resolve()))
        self.assertEqual(
            metadata["website_repo_path"], str(self.website_repo.resolve())
        )
        self.assertEqual(
            metadata["website_content_path"],
            str(result.destination_path.resolve()),
        )
        self.assertEqual(metadata["website_slug"], SLUG)
        self.assertEqual(
            metadata["website_local_url"],
            f"http://localhost:5173/blog/{SLUG}",
        )
        self.assertEqual(metadata["approved_at"], "2026-07-06T19:00:00+00:00")

    def test_approval_changes_only_status_to_published(self):
        source = self.write_post()
        original = source.read_text(encoding="utf-8")
        self.approve()
        approved = source.read_text(encoding="utf-8")

        self.assertIn('status: "published"', approved)
        self.assertEqual(
            approved.replace('status: "published"', 'status: "draft"'),
            original,
        )

    def test_dry_run_does_not_modify_files_or_metadata(self):
        source = self.write_post()
        original = source.read_text(encoding="utf-8")
        state_path = self.output_dir / "publish-state.json"
        original_state = state_path.read_text(encoding="utf-8")

        result = self.approve(dry_run=True)

        self.assertTrue(result.dry_run)
        self.assertFalse(result.destination_path.exists())
        self.assertEqual(source.read_text(encoding="utf-8"), original)
        self.assertEqual(state_path.read_text(encoding="utf-8"), original_state)

    def test_existing_destination_blocks_without_force(self):
        source = self.write_post()
        destination = (
            self.website_repo / "src" / "content" / "blog" / source.name
        )
        destination.parent.mkdir(parents=True)
        destination.write_text("existing", encoding="utf-8")

        with self.assertRaisesRegex(ApprovalError, "already exists"):
            self.approve()

        self.assertEqual(destination.read_text(encoding="utf-8"), "existing")
        self.assertIn('status: "draft"', source.read_text(encoding="utf-8"))

    def test_force_overwrites_existing_destination(self):
        source = self.write_post()
        destination = (
            self.website_repo / "src" / "content" / "blog" / source.name
        )
        destination.parent.mkdir(parents=True)
        destination.write_text("existing", encoding="utf-8")

        result = self.approve(force=True)

        self.assertTrue(result.overwritten)
        self.assertIn(
            'status: "published"',
            destination.read_text(encoding="utf-8"),
        )
        self.assertNotEqual(destination.read_text(encoding="utf-8"), "existing")

    def test_missing_post_has_clear_error(self):
        with self.assertRaisesRegex(ApprovalError, "No generated blog post found"):
            self.approve()

    def test_multiple_posts_for_date_have_clear_error(self):
        self.write_post()
        (self.output_dir / "2026-07-06-another-post.md").write_text(
            markdown(), encoding="utf-8"
        )

        with self.assertRaisesRegex(ApprovalError, "Expected exactly one post"):
            self.approve()

    def test_failed_quality_review_cannot_be_approved(self):
        self.write_post(publish_status="failed", quality_status="failed")

        with self.assertRaisesRegex(ApprovalError, "failed the editorial quality"):
            self.approve()

    def test_frontmatter_date_mismatch_blocks_approval(self):
        self.write_post(content=markdown(post_date="2026-07-05"))

        with self.assertRaisesRegex(ApprovalError, "does not match"):
            self.approve()

    def test_missing_required_frontmatter_blocks_approval(self):
        self.write_post(content=markdown(include_title=False))

        with self.assertRaisesRegex(ApprovalError, 'missing required frontmatter "title"'):
            self.approve()

    def test_unusable_missing_slug_blocks_approval(self):
        content = markdown().replace(f'slug: "{SLUG}"\n', "")
        self.write_post(filename="2026-07-06-.md", content=content)

        with self.assertRaisesRegex(ApprovalError, "no usable slug"):
            self.approve()

    def test_approval_passes_with_valid_sources(self):
        self.write_post()
        result = self.approve()

        self.assertTrue(result.sources_eligible)
        self.assertTrue(result.sources_visible_present)
        self.assertEqual(result.sources_frontmatter_count, 3)
        self.assertTrue(result.sources_coverage_pass)

    def test_approval_fails_when_frontmatter_sources_missing(self):
        self.write_post(content=markdown(include_sources=False))

        with self.assertRaisesRegex(
            ApprovalError, "no valid source URLs"
        ):
            self.approve()

    def test_approval_fails_when_visible_sources_section_missing(self):
        content = markdown(body_sources_section="")
        self.write_post(content=content)

        with self.assertRaisesRegex(
            ApprovalError, "missing visible Sources section"
        ):
            self.approve()

    def test_approval_fails_when_source_coverage_below_threshold(self):
        content = markdown(minimum_sources_required=5)
        self.write_post(content=content)

        with self.assertRaisesRegex(
            ApprovalError,
            r"Source coverage below threshold: 3 valid sources found, 5 expected",
        ):
            self.approve()

    def test_sources_missing_marker_blocks_approval(self):
        content = markdown(minimum_sources_required=0, include_sources=False)
        self.write_post(content=content)

        with self.assertRaisesRegex(ApprovalError, "sources_missing"):
            self.approve()

    def test_dry_run_reports_source_readiness(self):
        self.write_post()
        result = self.approve(dry_run=True)

        self.assertTrue(result.dry_run)
        self.assertTrue(result.sources_eligible)
        self.assertTrue(result.sources_visible_present)
        self.assertEqual(result.sources_frontmatter_count, 3)
        self.assertEqual(result.sources_required_minimum, 3)

    def test_dry_run_does_not_raise_on_missing_sources(self):
        content = markdown(include_sources=False)
        self.write_post(content=content)

        result = self.approve(dry_run=True)

        self.assertTrue(result.dry_run)
        self.assertFalse(result.sources_eligible)
        self.assertEqual(result.sources_frontmatter_count, 0)


if __name__ == "__main__":
    unittest.main()
