import unittest
from unittest.mock import MagicMock, patch

from blog.rewriter import BlogArticleRewriter, RewriteResult


class TestBlogArticleRewriter(unittest.TestCase):
    def test_no_provider_returns_original(self):
        rewriter = BlogArticleRewriter(provider="none")
        self.assertFalse(rewriter.is_available())
        res = rewriter.rewrite(
            title="Original Title",
            subtitle="Original Subtitle",
            excerpt="Original Excerpt",
            body_markdown="## Original Body\n\nContent here.",
        )
        self.assertEqual(res.title, "Original Title")
        self.assertEqual(res.body_markdown, "## Original Body\n\nContent here.")

    @patch("google.genai.Client")
    def test_gemini_rewrite_success(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = '{"title": "Polished Title", "subtitle": "Polished Subtitle", "excerpt": "Polished Excerpt", "body_markdown": "## Polished Body\\n\\nNew prose."}'
        mock_client.models.generate_content.return_value = mock_response

        rewriter = BlogArticleRewriter(provider="gemini", gemini_api_key="test-key", gemini_model="gemini-3.8-flash")
        self.assertTrue(rewriter.is_available())
        res = rewriter.rewrite("Old", "Old", "Old", "Old")
        self.assertEqual(res.title, "Polished Title")
        self.assertEqual(res.body_markdown, "## Polished Body\n\nNew prose.")

    @patch("httpx.post")
    def test_openai_rewrite_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": '{"title": "OpenAI Title", "subtitle": "OpenAI Sub", "excerpt": "OpenAI Ex", "body_markdown": "## Strategic Read\\n\\nProse."}'
                }
            }]
        }
        mock_post.return_value = mock_response

        rewriter = BlogArticleRewriter(provider="openai", openai_api_key="sk-test", openai_model="gpt-4o-mini")
        self.assertTrue(rewriter.is_available())
        res = rewriter.rewrite("Old", "Old", "Old", "Old")
        self.assertEqual(res.title, "OpenAI Title")
        self.assertEqual(res.body_markdown, "## Strategic Read\n\nProse.")


if __name__ == "__main__":
    unittest.main()
