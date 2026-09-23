import unittest

from web_gather.extract import extract_page


ARTICLE_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta property="og:title" content="A Headline">
<meta property="og:description" content="A short summary.">
<meta name="author" content="Jane Doe">
<link rel="canonical" href="https://news.com/story/canonical">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"NewsArticle",
 "headline":"A Headline",
 "datePublished":"2026-01-02T10:00:00Z",
 "author":{"@type":"Person","name":"John Smith"}}
</script>
</head>
<body>
<article>
<h1>A Headline</h1>
<p>This is the first paragraph of the story. It contains real news content
that density-based extractors should keep.</p>
<p>This is a second paragraph with more substantial reporting about the
event, including names and dates that make it look like prose.</p>
</article>
<nav>
<a href="/sports">Sports</a>
</nav>
<img src="/assets/photo.jpg" alt="img">
</body>
</html>
"""


class ExtractPageTest(unittest.TestCase):
    def test_extracts_headline_and_metadata(self):
        result = extract_page(ARTICLE_HTML, "https://news.com/story/1")
        self.assertIsNotNone(result["text"])
        self.assertTrue(len(result["text"]) > 80)
        self.assertEqual(result["title"], "A Headline")
        self.assertIn("Jane Doe", (result["byline"] or ""))
        self.assertEqual(result["published_utc"], "2026-01-02T10:00:00Z")
        self.assertEqual(result["summary"], "A short summary.")
        self.assertTrue(any("Headline" in h for h in result["headings"]))

    def test_domeration_collects_links_and_images(self):
        result = extract_page(ARTICLE_HTML, "https://news.com/story/1")
        self.assertIn("https://news.com/sports", result["links"])
        self.assertTrue(any("photo.jpg" in i for i in result["images"]))

    def test_no_clean_text_marks_empty(self):
        junk = "<html><body><p>Nav | © 2026 | Privacy</p></body></html>"
        result = extract_page(junk, "https://example.com/")
        self.assertFalse((result["text"] or "").strip())

    def test_json_ld_date_normalized(self):
        html = """<html><head><script type="application/ld+json">
        {"@type":"Article","datePublished":"2025-05-01T08:30:00Z"}
        </script></head><body><p>Some fairly long piece of genuine article
        text here describing things in full sentences.</p></body></html>"""
        result = extract_page(html, "https://x.com/a")
        self.assertEqual(result["published_utc"], "2025-05-01T08:30:00Z")


if __name__ == "__main__":
    unittest.main()