import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main
from blog.config import BlogConfig
from blog.models import BlogPost, PublishResult, QualityReport
from blog.publishers import (
    LocalBlogPublisher,
    PublishStateStore,
    WebsiteBlogPublisher,
)
from blog.quality import BlogQualityGate
from blog.service import BlogPublishingService
from blog.transformer import BlogArticleTransformer
from digest_models import Digest
from main import deliver


DAY = date(2026, 7, 6)

_SOURCED_ARTICLES_BY_TOPIC = {
    "AI & Technology": [
        {
            "source": "TechCrunch",
            "title": "Alibaba reportedly bans employees from using Claude Code",
            "summary": "Alibaba has barred staff from using Claude Code.",
            "url": (
                "https://techcrunch.com/2026/07/04/"
                "alibaba-reportedly-bans-employees-from-using-claude-code/"
            ),
            "published": "2026-07-04",
        },
        {
            "source": "TechCrunch",
            "title": "Amazon will stop accepting new customers for Mechanical Turk",
            "summary": "Amazon is winding down new sign-ups for Mechanical Turk.",
            "url": (
                "https://techcrunch.com/2026/07/05/"
                "amazon-will-stop-accepting-new-customers-for-mechanical-turk/"
            ),
            "published": "2026-07-05",
        },
    ]
}


class _FakeMessage:
    def __init__(self, text):
        self.content = [SimpleNamespace(type="text", text=text)]


class _FakeMessages:
    def __init__(self, payload_json):
        self.payload_json = payload_json

    def create(self, **kwargs):
        return _FakeMessage(self.payload_json)


class _FakeAnthropicClient:
    def __init__(self, payload_json):
        self.messages = _FakeMessages(payload_json)


def _sourced_transform_payload(source_ids=("S001", "S002")):
    return json.dumps({
        "title": "Capital Is Moving Toward the Constraint That Matters",
        "subtitle": "The day's signals point to a shift toward control.",
        "excerpt": "A focused reading of the evidence and its implications.",
        "body_markdown": (
            "The central question is no longer whether the shift will "
            "happen but who controls the constraint that matters most for "
            "the years ahead as capability spreads unevenly across firms.\n\n"
            "## The Constraint\n\nAnalysis of the constraint.\n\n"
            "## The Operating Choice\n\nAnalysis of the choice at hand.\n\n"
            "## The Strategic Read\n\nThe conclusion follows directly."
        ),
        "tags": ["Strategy", "Technology", "Capital"],
        "seo_meta_description": "A source-grounded analysis of the signals.",
        "slug": "capital-moves-toward-the-constraint",
        "source_ids": list(source_ids),
    })


def sample_post(word_count=920):
    words = " ".join(["evidence"] * word_count)
    return BlogPost(
        title="Capital Is Moving Toward the Constraint That Matters",
        subtitle="The day's signals point to a shift from experimentation to control.",
        slug="capital-moves-toward-the-constraint",
        date=DAY,
        author="Gabriel Odeyemi",
        body_markdown=(
            "The central question is no longer whether the shift will happen. "
            "The available evidence shows where operating control will matter "
            "and why leaders must distinguish timing from conviction. "
            + words
            + "\n\n## The Constraint\n\nAnalysis.\n\n"
            "## The Operating Choice\n\nAnalysis.\n\n"
            "## The Strategic Read\n\nConclusion."
        ),
        excerpt="A focused reading of the evidence and its operating implications.",
        tags=["Strategy", "Technology", "Capital"],
        seo_meta_description="A source-grounded analysis of the day's strategic signals.",
        source_digest_date=DAY,
        source_digest_id="strategic-digest-2026-07-06",
        canonical_url=(
            "https://gabrielodeyemi.com/blog/"
            "capital-moves-toward-the-constraint"
        ),
    )


class LocalPublisherTests(unittest.TestCase):
    def test_same_digest_date_is_skipped(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = replace(
                BlogConfig(),
                output_dir=Path(temporary),
                existing_post_action="skip",
            )
            publisher = LocalBlogPublisher(config)
            first = publisher.publish(sample_post())
            second = publisher.publish(sample_post())

            self.assertFalse(first.skipped)
            self.assertTrue(second.skipped)
            self.assertEqual(
                len(list(Path(temporary).glob("*.md"))),
                1,
            )

    def test_state_contains_required_publication_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = replace(BlogConfig(), output_dir=Path(temporary))
            LocalBlogPublisher(config).publish(sample_post())
            state = PublishStateStore(Path(temporary)).get(DAY.isoformat())

            for key in (
                "title",
                "slug",
                "date",
                "source_digest_date",
                "source_digest_id",
                "canonical_url",
                "publish_status",
            ):
                self.assertIn(key, state)

    def test_update_removes_previous_same_day_slug(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = replace(
                BlogConfig(),
                output_dir=Path(temporary),
                existing_post_action="update",
            )
            publisher = LocalBlogPublisher(config)
            first = publisher.publish(sample_post())
            revised = sample_post()
            revised.slug = "a-better-same-day-slug"
            revised.canonical_url = (
                "https://gabrielodeyemi.com/blog/a-better-same-day-slug"
            )
            second = publisher.publish(revised)

            self.assertFalse(first.artifact_path.exists())
            self.assertTrue(second.artifact_path.exists())
            self.assertEqual(len(list(Path(temporary).glob("*.md"))), 1)

    def test_repository_failure_falls_back_to_local_draft(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = replace(
                BlogConfig(),
                mode="repository",
                output_dir=root / "output",
                website_repo_path=root / "not-a-repository",
                default_status="published",
                approval_required=False,
            )
            result = WebsiteBlogPublisher(config).publish(sample_post())

            self.assertEqual(result.publisher, "local-fallback")
            self.assertEqual(result.status, "draft")
            self.assertTrue(result.artifact_path.exists())

    def test_approval_requirement_prevents_repository_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "website"
            (repository / ".git").mkdir(parents=True)
            config = replace(
                BlogConfig(),
                mode="repository",
                output_dir=root / "output",
                website_repo_path=repository,
                default_status="published",
                approval_required=True,
            )
            result = WebsiteBlogPublisher(config).publish(sample_post())

            self.assertEqual(result.publisher, "local-approval-required")
            self.assertEqual(result.status, "draft")
            self.assertFalse((repository / "src" / "content" / "blog").exists())


def _sourced_digest():
    return Digest.create("Briefing text.", _SOURCED_ARTICLES_BY_TOPIC, DAY)


def _sourced_sample_post():
    post = sample_post()
    post.sources = [
        {
            "title": "Alibaba reportedly bans employees from using Claude Code",
            "url": (
                "https://techcrunch.com/2026/07/04/"
                "alibaba-reportedly-bans-employees-from-using-claude-code/"
            ),
            "publisher": "TechCrunch",
            "date": "2026-07-04",
        },
    ]
    post.minimum_sources_required = 1
    post.body_markdown += (
        "\n\n## Sources\n\n"
        "- [Alibaba reportedly bans employees from using Claude Code]"
        "(https://techcrunch.com/2026/07/04/"
        "alibaba-reportedly-bans-employees-from-using-claude-code/), "
        "TechCrunch, 2026-07-04"
    )
    return post


class QualityGateTests(unittest.TestCase):
    def test_rejects_em_dash_and_unknown_source_link(self):
        config = replace(BlogConfig(), quality_review_enabled=False)
        post = sample_post()
        post.body_markdown += (
            "\n\nA claim — with an "
            "[unapproved source](https://example.com/not-in-digest)."
        )
        report = BlogQualityGate(config).evaluate(
            post, Digest.create("Briefing", {}, DAY)
        )

        self.assertFalse(report.passed)
        self.assertTrue(any("em dash" in issue for issue in report.issues))
        self.assertTrue(any("URLs absent" in issue for issue in report.issues))
        self.assertTrue(any("sources_missing" in issue for issue in report.issues))

    def test_passes_with_sufficient_valid_sources(self):
        config = replace(BlogConfig(), quality_review_enabled=False)
        report = BlogQualityGate(config).evaluate(
            _sourced_sample_post(), _sourced_digest()
        )

        self.assertTrue(report.passed, report.issues)

    def test_flags_source_coverage_below_threshold(self):
        config = replace(BlogConfig(), quality_review_enabled=False)
        post = _sourced_sample_post()
        post.minimum_sources_required = 3

        report = BlogQualityGate(config).evaluate(post, _sourced_digest())

        self.assertFalse(report.passed)
        self.assertTrue(
            any(
                "Source coverage below threshold" in issue
                for issue in report.issues
            )
        )

    def test_flags_missing_visible_sources_section(self):
        config = replace(BlogConfig(), quality_review_enabled=False)
        post = _sourced_sample_post()
        post.body_markdown = post.body_markdown.split("## Sources")[0].strip()

        report = BlogQualityGate(config).evaluate(post, _sourced_digest())

        self.assertFalse(report.passed)
        self.assertTrue(
            any("visible" in issue and "Sources" in issue for issue in report.issues)
        )


class TransformerSourcesTests(unittest.TestCase):
    def test_transform_appends_deterministic_sources_section(self):
        digest = _sourced_digest()
        client = _FakeAnthropicClient(_sourced_transform_payload())
        config = replace(BlogConfig(), minimum_words=10, maximum_words=5000)
        transformer = BlogArticleTransformer(config, client=client, model="fake")

        post = transformer.transform(digest)

        self.assertIn("## Sources", post.body_markdown)
        self.assertIn(
            "[Alibaba reportedly bans employees from using Claude Code]"
            "(https://techcrunch.com/2026/07/04/"
            "alibaba-reportedly-bans-employees-from-using-claude-code/)",
            post.body_markdown,
        )
        self.assertEqual(len(post.sources), 2)
        self.assertEqual(post.minimum_sources_required, 2)

    def test_transform_frontmatter_includes_structured_sources(self):
        digest = _sourced_digest()
        client = _FakeAnthropicClient(_sourced_transform_payload())
        config = replace(BlogConfig(), minimum_words=10, maximum_words=5000)
        transformer = BlogArticleTransformer(config, client=client, model="fake")

        post = transformer.transform(digest)
        markdown_text = post.to_markdown()

        self.assertIn("sources:", markdown_text)
        self.assertIn(
            'url: "https://techcrunch.com/2026/07/04/'
            'alibaba-reportedly-bans-employees-from-using-claude-code/"',
            markdown_text,
        )
        self.assertIn("minimum_sources_required: 2", markdown_text)

    def test_transform_excludes_cards_with_invalid_urls(self):
        articles_by_topic = {
            "AI & Technology": [
                {
                    "source": "TechCrunch",
                    "title": "A story with no URL",
                    "summary": "Summary.",
                    "url": "",
                    "published": "2026-07-06",
                },
            ]
        }
        digest = Digest.create("Briefing.", articles_by_topic, DAY)
        client = _FakeAnthropicClient(
            _sourced_transform_payload(source_ids=["S001"])
        )
        config = replace(BlogConfig(), minimum_words=10, maximum_words=5000)
        transformer = BlogArticleTransformer(config, client=client, model="fake")

        post = transformer.transform(digest)

        self.assertEqual(post.sources, [])
        self.assertIn("No verifiable source metadata", post.body_markdown)


class RegenerateCommandTests(unittest.TestCase):
    def test_regenerate_reloads_digest_and_keeps_draft(self):
        with tempfile.TemporaryDirectory() as temporary:
            digest_dir = Path(temporary) / "digests"
            digest = _sourced_digest()
            digest.save(digest_dir)

            captured = {}

            class FakeService:
                def __init__(self, config):
                    captured["config"] = config

                def publish(self, digest_arg):
                    captured["digest"] = digest_arg
                    return PublishResult(
                        status="draft",
                        canonical_url="https://gabrielodeyemi.com/blog/example",
                        artifact_path=Path(temporary) / "output" / "post.md",
                        publisher="local",
                        message="Wrote local blog artifact.",
                    )

            args = SimpleNamespace(regenerate_date=DAY, digest_dir=digest_dir)
            with patch("main.BlogPublishingService", FakeService):
                exit_code = main.run_blog_regenerate(args)

            self.assertEqual(exit_code, 0)
            self.assertEqual(captured["digest"].digest_id, digest.digest_id)
            self.assertEqual(
                captured["digest"].distinct_source_urls(),
                digest.distinct_source_urls(),
            )
            self.assertEqual(captured["config"].mode, "local")
            self.assertEqual(captured["config"].default_status, "draft")
            self.assertEqual(captured["config"].existing_post_action, "update")

    def test_regenerate_without_snapshot_fails_clearly(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = SimpleNamespace(
                regenerate_date=DAY, digest_dir=Path(temporary) / "missing"
            )
            exit_code = main.run_blog_regenerate(args)
            self.assertEqual(exit_code, 2)


class OrchestrationTests(unittest.TestCase):
    def test_blog_failure_does_not_block_notion_or_email(self):
        calls = []
        digest = Digest.create("Briefing", {}, DAY)

        def notion(briefing):
            calls.append(("notion", briefing))
            return "https://notion.example/digest"

        def email(briefing, notion_url):
            calls.append(("email", briefing, notion_url))

        def blog(_digest):
            calls.append(("blog",))
            raise RuntimeError("simulated website failure")

        deliver(digest, notion_push=notion, email_send=email, blog_publish=blog)
        self.assertEqual([call[0] for call in calls], ["notion", "email", "blog"])

    def test_service_retries_quality_failure_then_publishes(self):
        class Transformer:
            def __init__(self):
                self.issues = []

            def transform(self, _digest, issues):
                self.issues.append(list(issues))
                return sample_post()

        class Gate:
            def __init__(self):
                self.calls = 0

            def evaluate(self, _post, _digest):
                self.calls += 1
                if self.calls == 1:
                    return QualityReport(False, ["Weak thesis."])
                return QualityReport(True, [])

        class Publisher:
            def __init__(self):
                self.called = False

            def publish(self, post):
                self.called = True
                return LocalBlogPublisher(config).publish(post)

        with tempfile.TemporaryDirectory() as temporary:
            config = replace(
                BlogConfig(),
                output_dir=Path(temporary),
                maximum_attempts=2,
            )
            transformer = Transformer()
            gate = Gate()
            publisher = Publisher()
            service = BlogPublishingService(
                config,
                transformer=transformer,
                quality_gate=gate,
                publisher=publisher,
            )
            service.publish(Digest.create("Briefing", {}, DAY))

            self.assertEqual(transformer.issues[1], ["Weak thesis."])
            self.assertTrue(publisher.called)


if __name__ == "__main__":
    unittest.main()
