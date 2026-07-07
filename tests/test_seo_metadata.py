"""Tests for the SEO/discoverability metadata feature:
seo_title, topic_cluster, primary_keyword, secondary_keywords,
internal_link_targets, suggested_related_posts.

Mirrors the existing test structure: BlogPost serialization (models),
BlogArticleTransformer output (transformer), blog:check readiness
(check + approval shared evaluator), and blog:regenerate.
"""

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from blog.approval import ApprovalError, approve_blog_post
from blog.check import run_check
from blog.config import BlogConfig
from blog.models import BlogPost
from blog.publishers import LocalBlogPublisher, PublishStateStore
from blog.seo import TOPIC_CLUSTERS, evaluate_seo_metadata
from blog.transformer import BlogArticleTransformer
from digest_models import Digest
from tests.test_approval import DAY, SLUG, TITLE, markdown
from tests.test_check import pmarkdown

DAY2 = date(2026, 7, 7)


def sample_post(**overrides) -> BlogPost:
    defaults = dict(
        title="Capital Is Moving Toward the Constraint That Matters",
        subtitle="The day's signals point to a shift toward control.",
        slug="capital-moves-toward-the-constraint",
        date=DAY,
        author="Gabriel Odeyemi",
        body_markdown=(
            "Opening paragraph.\n\n## The Strategic Read\n\nConclusion."
        ),
        excerpt="A focused reading of the evidence.",
        tags=["Strategy", "Technology"],
        seo_meta_description="A source-grounded analysis.",
        source_digest_date=DAY,
        source_digest_id="strategic-digest-2026-07-06",
        canonical_url="https://gabrielodeyemi.com/blog/capital-moves-toward-the-constraint",
    )
    defaults.update(overrides)
    return BlogPost(**defaults)


class BlogPostSeoSerializationTests(unittest.TestCase):
    """1. BlogPost serializes new SEO fields into frontmatter."""

    def test_serializes_seo_fields_into_frontmatter(self):
        post = sample_post(
            seo_title="AI Trust, Governance, and Competitive Advantage",
            topic_cluster="AI Governance",
            primary_keyword="AI governance and trust",
            secondary_keywords=["enterprise AI adoption", "AI risk management", "AI data control"],
            internal_link_targets=[
                {"label": "Strategic Digest", "url": "/blog", "reason": "Archive."},
                {
                    "label": "AI Strategy & Operations Consulting",
                    "url": "/ai-consulting",
                    "reason": "Discusses AI governance.",
                    "status": "planned",
                },
            ],
            suggested_related_posts=[
                {
                    "title": "The Trust Gate",
                    "url": "/blog/ai-trust-gate-control-not-capability",
                    "reason": "Related analysis.",
                }
            ],
        )
        markdown_text = post.to_markdown()

        self.assertIn('seo_title: "AI Trust, Governance, and Competitive Advantage"', markdown_text)
        self.assertIn('topic_cluster: "AI Governance"', markdown_text)
        self.assertIn('primary_keyword: "AI governance and trust"', markdown_text)
        self.assertIn(
            'secondary_keywords: ["enterprise AI adoption", "AI risk management", "AI data control"]',
            markdown_text,
        )
        self.assertIn("internal_link_targets:", markdown_text)
        self.assertIn('    url: "/ai-consulting"', markdown_text)
        self.assertIn('    status: "planned"', markdown_text)
        self.assertIn("suggested_related_posts:", markdown_text)
        self.assertIn('    url: "/blog/ai-trust-gate-control-not-capability"', markdown_text)

    def test_empty_seo_fields_serialize_as_empty_yaml_lists_or_strings(self):
        markdown_text = sample_post().to_markdown()

        self.assertIn('seo_title: ""', markdown_text)
        self.assertIn('topic_cluster: ""', markdown_text)
        self.assertIn("secondary_keywords: []", markdown_text)
        self.assertIn("internal_link_targets: []", markdown_text)
        self.assertIn("suggested_related_posts: []", markdown_text)


class SeoMetadataValidationTests(unittest.TestCase):
    """Direct unit tests of the pure blog.seo.evaluate_seo_metadata policy."""

    def _valid_frontmatter(self):
        return {
            "seo_title": "A specific, explicit search title",
            "topic_cluster": "AI Governance",
            "primary_keyword": "AI governance and trust",
            "secondary_keywords": ["enterprise AI adoption", "AI risk management", "AI data control"],
            "internal_link_targets": [{"label": "Strategic Digest", "url": "/blog"}],
            "suggested_related_posts": [],
        }

    def test_valid_metadata_has_no_warnings_or_blockers(self):
        result = evaluate_seo_metadata(self._valid_frontmatter())
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["blockers"], [])

    def test_missing_metadata_only_warns(self):
        result = evaluate_seo_metadata({})
        self.assertEqual(result["blockers"], [])
        self.assertTrue(any("seo_title" in w for w in result["warnings"]))
        self.assertTrue(any("topic_cluster" in w for w in result["warnings"]))
        self.assertTrue(any("primary_keyword" in w for w in result["warnings"]))
        self.assertTrue(any("secondary_keywords" in w for w in result["warnings"]))
        self.assertTrue(any("internal_link_targets" in w for w in result["warnings"]))

    def test_invalid_topic_cluster_blocks(self):
        frontmatter = self._valid_frontmatter()
        frontmatter["topic_cluster"] = "Not A Real Cluster"
        result = evaluate_seo_metadata(frontmatter)

        self.assertTrue(any("topic_cluster" in b for b in result["blockers"]))
        self.assertNotIn("Not A Real Cluster", TOPIC_CLUSTERS)

    def test_invalid_internal_link_url_blocks(self):
        frontmatter = self._valid_frontmatter()
        frontmatter["internal_link_targets"] = [
            {"label": "Bogus", "url": "https://evil.example.com/spam"}
        ]
        result = evaluate_seo_metadata(frontmatter)

        self.assertTrue(any("internal_link_targets" in b for b in result["blockers"]))

    def test_unknown_related_post_url_blocks(self):
        frontmatter = self._valid_frontmatter()
        frontmatter["suggested_related_posts"] = [
            {"title": "Invented Post", "url": "/blog/invented-post-that-does-not-exist"}
        ]
        result = evaluate_seo_metadata(frontmatter, known_post_urls={"/blog/real-post"})

        self.assertTrue(any("suggested_related_posts" in b for b in result["blockers"]))

    def test_known_related_post_url_does_not_block(self):
        frontmatter = self._valid_frontmatter()
        frontmatter["suggested_related_posts"] = [
            {"title": "Real Post", "url": "/blog/real-post"}
        ]
        result = evaluate_seo_metadata(frontmatter, known_post_urls={"/blog/real-post"})

        self.assertEqual(result["blockers"], [])

    def test_secondary_keywords_below_minimum_warns_not_blocks(self):
        frontmatter = self._valid_frontmatter()
        frontmatter["secondary_keywords"] = ["only one keyword"]
        result = evaluate_seo_metadata(frontmatter)

        self.assertEqual(result["blockers"], [])
        self.assertTrue(any("secondary_keywords" in w for w in result["warnings"]))

    def test_secondary_keywords_above_maximum_warns_not_blocks(self):
        frontmatter = self._valid_frontmatter()
        frontmatter["secondary_keywords"] = [f"keyword {i}" for i in range(9)]
        result = evaluate_seo_metadata(frontmatter)

        self.assertEqual(result["blockers"], [])
        self.assertTrue(any("secondary_keywords" in w for w in result["warnings"]))

    def test_malformed_internal_link_targets_blocks(self):
        frontmatter = self._valid_frontmatter()
        frontmatter["internal_link_targets"] = "not-a-list"
        result = evaluate_seo_metadata(frontmatter)

        self.assertTrue(any("internal_link_targets" in b for b in result["blockers"]))


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


def _transform_payload(**overrides):
    payload = {
        "title": "Capital Is Moving Toward the Constraint That Matters",
        "subtitle": "The day's signals point to a shift toward control.",
        "excerpt": "A focused reading of the evidence and its implications.",
        "body_markdown": (
            "Opening thesis paragraph with enough words to pass the "
            "minimum length gate for this fixture in the test suite here.\n\n"
            "## The Constraint\n\nAnalysis.\n\n## The Strategic Read\n\nConclusion."
        ),
        "tags": ["Strategy", "Technology", "Capital"],
        "seo_meta_description": "A source-grounded analysis of the signals.",
        "slug": "capital-moves-toward-the-constraint",
        "source_ids": [],
        "seo_title": "Enterprise Capital Allocation and Operating Control",
        "topic_cluster": "Strategy & Operations",
        "primary_keyword": "enterprise capital allocation",
        "secondary_keywords": [
            "operating model strategy",
            "capital allocation discipline",
            "corporate strategy signals",
        ],
        "internal_link_targets": [
            {"label": "Strategic Digest", "url": "/blog", "reason": "Archive."},
            {"label": "Off-limits page", "url": "https://not-allowed.example.com"},
        ],
        "suggested_related_posts": [],
    }
    payload.update(overrides)
    return json.dumps(payload)


class TransformerSeoTests(unittest.TestCase):
    """2. Transformer includes a valid topic_cluster from the controlled list,
    and defensively filters anything that is not on an allowed list."""

    def _digest(self, day=DAY):
        return Digest.create("Briefing text.", {}, day)

    def test_transform_includes_valid_controlled_topic_cluster(self):
        client = _FakeAnthropicClient(_transform_payload())
        config = replace(BlogConfig(), minimum_words=5, maximum_words=5000)
        transformer = BlogArticleTransformer(config, client=client, model="fake")

        post = transformer.transform(self._digest())

        self.assertIn(post.topic_cluster, TOPIC_CLUSTERS)
        self.assertEqual(post.topic_cluster, "Strategy & Operations")

    def test_transform_drops_invalid_topic_cluster_instead_of_inventing(self):
        client = _FakeAnthropicClient(
            _transform_payload(topic_cluster="Something Made Up")
        )
        config = replace(BlogConfig(), minimum_words=5, maximum_words=5000)
        transformer = BlogArticleTransformer(config, client=client, model="fake")

        post = transformer.transform(self._digest())

        self.assertEqual(post.topic_cluster, "")

    def test_transform_filters_out_of_universe_internal_link_target(self):
        client = _FakeAnthropicClient(_transform_payload())
        config = replace(BlogConfig(), minimum_words=5, maximum_words=5000)
        transformer = BlogArticleTransformer(config, client=client, model="fake")

        post = transformer.transform(self._digest())

        urls = [t["url"] for t in post.internal_link_targets]
        self.assertIn("/blog", urls)
        self.assertNotIn("https://not-allowed.example.com", urls)
        self.assertEqual(len(post.internal_link_targets), 1)

    def test_transform_filters_unknown_related_post(self):
        client = _FakeAnthropicClient(
            _transform_payload(
                suggested_related_posts=[
                    {"title": "Invented", "url": "/blog/invented-post"}
                ]
            )
        )
        config = replace(BlogConfig(), minimum_words=5, maximum_words=5000)
        transformer = BlogArticleTransformer(config, client=client, model="fake")

        post = transformer.transform(self._digest())

        self.assertEqual(post.suggested_related_posts, [])

    def test_transform_recommends_a_real_known_related_post(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            existing = (
                "---\n"
                'title: "The Trust Gate"\n'
                'slug: "ai-trust-gate-control-not-capability"\n'
                'canonical_url: "https://gabrielodeyemi.com/blog/ai-trust-gate-control-not-capability"\n'
                'status: "published"\n'
                "---\n\nBody.\n"
            )
            (output_dir / "2026-07-06-ai-trust-gate-control-not-capability.md").write_text(
                existing, encoding="utf-8"
            )

            client = _FakeAnthropicClient(
                _transform_payload(
                    suggested_related_posts=[
                        {
                            "title": "The Trust Gate",
                            "url": "/blog/ai-trust-gate-control-not-capability",
                            "reason": "Related governance analysis.",
                        }
                    ]
                )
            )
            config = replace(
                BlogConfig(), minimum_words=5, maximum_words=5000, output_dir=output_dir
            )
            transformer = BlogArticleTransformer(config, client=client, model="fake")

            post = transformer.transform(self._digest(DAY2))

            self.assertEqual(len(post.suggested_related_posts), 1)
            self.assertEqual(
                post.suggested_related_posts[0]["url"],
                "/blog/ai-trust-gate-control-not-capability",
            )


class CheckSeoTests(unittest.TestCase):
    """3/4/5/6. blog:check warns on missing SEO metadata, blocks on invalid
    topic_cluster and invalid internal link URLs, and warns (not blocks) on
    out-of-range secondary_keywords, per the chosen rollout-safety policy."""

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

    def write_post(self, *, content=None, filename=f"2026-07-06-{SLUG}.md"):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        source = self.output_dir / filename
        source.write_text(content or pmarkdown(), encoding="utf-8")
        metadata = {
            "title": TITLE,
            "slug": SLUG,
            "date": DAY.isoformat(),
            "source_digest_date": DAY.isoformat(),
            "source_digest_id": f"strategic-digest-{DAY.isoformat()}",
            "canonical_url": f"https://gabrielodeyemi.com/blog/{SLUG}",
            "artifact_path": str(source.resolve()),
            "publish_status": "draft",
            "quality_gate_status": "passed",
        }
        PublishStateStore(self.output_dir).save(DAY.isoformat(), metadata)
        return source

    def check(self):
        return run_check(DAY, self.config)

    def test_check_warns_when_seo_metadata_missing(self):
        self.write_post(content=pmarkdown(include_seo=False))
        result = self.check()

        self.assertTrue(result.ready)
        self.assertEqual(result.result_label, "READY with warnings")
        self.assertTrue(any("seo_title" in w for w in result.warnings))
        self.assertTrue(any("topic_cluster" in w for w in result.warnings))

    def test_invalid_topic_cluster_blocks_readiness(self):
        self.write_post(content=pmarkdown(topic_cluster="Not A Real Cluster"))
        result = self.check()

        self.assertFalse(result.ready)
        self.assertEqual(result.exit_code, 2)
        self.assertTrue(any("topic_cluster" in b for b in result.blockers))

    def test_invalid_internal_link_url_blocks_readiness(self):
        links_yaml = (
            "internal_link_targets:\n"
            '  - label: "Bogus"\n'
            '    url: "https://evil.example.com/spam"\n'
        )
        self.write_post(content=pmarkdown(internal_link_targets_yaml=links_yaml))
        result = self.check()

        self.assertFalse(result.ready)
        self.assertTrue(any("internal_link_targets" in b for b in result.blockers))

    def test_secondary_keywords_below_three_warns_not_blocks(self):
        self.write_post(content=pmarkdown(secondary_keywords=["only one"]))
        result = self.check()

        self.assertTrue(result.ready)
        self.assertTrue(any("secondary_keywords" in w for w in result.warnings))

    def test_secondary_keywords_above_seven_warns_not_blocks(self):
        self.write_post(
            content=pmarkdown(secondary_keywords=[f"keyword {i}" for i in range(9)])
        )
        result = self.check()

        self.assertTrue(result.ready)
        self.assertTrue(any("secondary_keywords" in w for w in result.warnings))

    def test_fully_valid_seo_metadata_has_no_seo_warnings(self):
        self.write_post()
        result = self.check()

        seo_messages = " ".join(item.message for item in result.seo_items)
        self.assertNotIn("missing", seo_messages)
        self.assertEqual(result.result_label, "READY")


class ApprovalSeoTests(unittest.TestCase):
    """7/8. Invalid SEO metadata blocks approval the same way it blocks
    blog:check, and approval still preserves the existing source-readiness
    behavior (sources and SEO are validated independently)."""

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

    def write_post(self, *, content=None):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        source = self.output_dir / f"2026-07-06-{SLUG}.md"
        source.write_text(content or markdown(), encoding="utf-8")
        metadata = {
            "title": TITLE,
            "slug": SLUG,
            "date": DAY.isoformat(),
            "source_digest_date": DAY.isoformat(),
            "source_digest_id": f"strategic-digest-{DAY.isoformat()}",
            "canonical_url": f"https://gabrielodeyemi.com/blog/{SLUG}",
            "artifact_path": str(source.resolve()),
            "publish_status": "draft",
            "quality_gate_status": "passed",
        }
        PublishStateStore(self.output_dir).save(DAY.isoformat(), metadata)
        return source

    def test_valid_seo_metadata_does_not_block_approval(self):
        self.write_post()
        result = approve_blog_post(DAY, self.config)

        self.assertTrue(result.destination_path.exists())

    def test_invalid_topic_cluster_blocks_approval(self):
        self.write_post(content=markdown(topic_cluster="Not A Real Cluster"))

        with self.assertRaisesRegex(ApprovalError, "topic_cluster"):
            approve_blog_post(DAY, self.config)

    def test_invalid_internal_link_url_blocks_approval(self):
        links_yaml = (
            "internal_link_targets:\n"
            '  - label: "Bogus"\n'
            '    url: "https://evil.example.com/spam"\n'
        )
        self.write_post(content=markdown(internal_link_targets_yaml=links_yaml))

        with self.assertRaisesRegex(ApprovalError, "internal_link_targets"):
            approve_blog_post(DAY, self.config)

    def test_missing_seo_metadata_does_not_block_approval(self):
        """Rollout safety: posts generated before this feature existed, or
        with no SEO metadata at all, must keep approving normally."""
        self.write_post(content=markdown(include_seo=False))
        result = approve_blog_post(DAY, self.config)

        self.assertTrue(result.destination_path.exists())

    def test_source_readiness_still_blocks_independently_of_seo(self):
        """Existing source-coverage behavior is untouched by the SEO gate:
        valid SEO metadata does not paper over a real source-readiness
        failure."""
        self.write_post(content=markdown(include_sources=False))

        with self.assertRaisesRegex(ApprovalError, "no valid source URLs"):
            approve_blog_post(DAY, self.config)


class RegenerateSeoTests(unittest.TestCase):
    """6. blog:regenerate keeps status draft and includes SEO fields."""

    def test_regenerated_artifact_is_draft_and_includes_seo_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "output" / "blog"
            client = _FakeAnthropicClient(_transform_payload())
            config = replace(
                BlogConfig(),
                mode="local",
                default_status="draft",
                existing_post_action="update",
                minimum_words=5,
                maximum_words=5000,
                output_dir=output_dir,
            )
            transformer = BlogArticleTransformer(config, client=client, model="fake")
            digest = Digest.create("Briefing.", {}, DAY)
            post = transformer.transform(digest)

            result = LocalBlogPublisher(config).publish(post)
            written = result.artifact_path.read_text(encoding="utf-8")

            self.assertIn('status: "draft"', written)
            self.assertIn('topic_cluster: "Strategy & Operations"', written)
            self.assertIn("secondary_keywords:", written)
            self.assertIn("internal_link_targets:", written)


if __name__ == "__main__":
    unittest.main()
