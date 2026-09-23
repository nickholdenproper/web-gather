import unittest

from web_gather.discover import (
    feed_entries,
    is_feed_payload,
    looks_like_feed,
    looks_like_sitemap,
    page_links,
    sitemap_urls,
)

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Feed</title>
  <entry><title>One</title><link href="https://news.com/a"/></entry>
  <entry><title>Two</title><link href="https://news.com/b"/></entry>
</feed>"""

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://site.com/a</loc></url>
  <url><loc>https://site.com/b</loc></url>
</urlset>"""

SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://site.com/sitemap2.xml</loc></sitemap>
</sitemapindex>"""


class DiscoverTest(unittest.TestCase):
    def test_feed_detection_and_entries(self):
        self.assertTrue(is_feed_payload(ATOM))
        self.assertEqual(feed_entries(ATOM), ["https://news.com/a", "https://news.com/b"])

    def test_sitemap_urls(self):
        pages, nested = sitemap_urls(SITEMAP, "https://site.com/sitemap.xml")
        self.assertEqual(pages, ["https://site.com/a", "https://site.com/b"])
        self.assertEqual(nested, [])

    def test_sitemap_index_nested(self):
        pages, nested = sitemap_urls(SITEMAP_INDEX, "https://site.com/sitemap.xml")
        self.assertEqual(pages, [])
        self.assertEqual(nested, ["https://site.com/sitemap2.xml"])

    def test_page_links_absolute(self):
        html = '<a href="https://ext.com/x">x</a><a href="/in">in</a>'
        links = page_links(html, "https://base.com/page")
        self.assertIn("https://ext.com/x", links)
        self.assertIn("https://base.com/in", links)

    def test_sitemap_feed_heuristics(self):
        self.assertTrue(looks_like_sitemap("https://x.com/sitemap_index.xml"))
        self.assertFalse(looks_like_sitemap("https://x.com/article"))
        self.assertTrue(looks_like_feed("https://x.com/feed"))
        self.assertTrue(looks_like_feed("https://x.com/rss"))
        self.assertTrue(looks_like_feed("https://x.com/atom.xml"))
        self.assertFalse(looks_like_feed("https://x.com/page"))


if __name__ == "__main__":
    unittest.main()