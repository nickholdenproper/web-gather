import unittest
from pathlib import Path

from web_gather.pipeline import PipelineOptions, crawl

from fake_fetcher import FakeFetcher

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><title>One</title><link href="https://news.com/a"/></entry>
  <entry><title>Two</title><link href="https://news.com/b"/></entry>
</feed>"""


def article_body(url: str, title: str) -> str:
    return f"""<html><head>
    <title>{title}</title>
    <meta name="author" content="Reporter">
    </head><body>
    <h1>{title}</h1>
    <p>This is the main body of the {title} story. It contains a good amount
    of real reporting prose so that the density extractor keeps it all as
    one clean article to store in the corpus.</p>
    <a href="https://news.com/a">Related</a>
    <a href="https://outside.com/other">External</a>
    </body></html>"""


def make_fetcher() -> FakeFetcher:
    fetcher = FakeFetcher()
    fetcher.add("https://news.com/feed", ATOM, headers={"content-type": "application/atom+xml"})
    fetcher.add("https://news.com/a", article_body("https://news.com/a", "Story A"), headers={"content-type": "application/xml"})
    fetcher.add("https://news.com/b", article_body("https://news.com/b", "Story B"))
    fetcher.add("https://news.com/dup1", article_body("https://news.com/dup1", "Dup"))
    fetcher.add("https://news.com/dup2", article_body("https://news.com/dup2", "Dup"))
    fetcher.add("https://news.com/err", "boom", status=500)
    fetcher.add("https://news.com/junk", "<p>nav footer link junk</p>")
    return fetcher


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__file__).parent / "_tmp_crawl"
        if self.tmp.exists():
            import shutil

            shutil.rmtree(self.tmp)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_feed_discovery_and_crawl(self):
        fetcher = make_fetcher()
        opts = PipelineOptions(max_pages=10, max_depth=2, out_dir=self.tmp)
        result = crawl(["https://news.com/feed"], opts, fetcher=fetcher)

        urls = [a.url for a in result.articles if a.status == "ok"]
        self.assertIn("https://news.com/a", urls)
        self.assertIn("https://news.com/b", urls)
        self.assertEqual(result.status.ok, 2)
        self.assertGreaterEqual(result.status.visited, 2)
        self.assertTrue(self.tmp.joinpath("corpus.txt").exists())

    def test_duplicate_content_collapsed(self):
        fetcher = FakeFetcher()
        fetcher.add("https://news.com/dup1", article_body("https://news.com/dup1", "Dup"))
        fetcher.add("https://news.com/dup2", article_body("https://news.com/dup2", "Dup"))
        opts = PipelineOptions(max_pages=5, max_depth=0, out_dir=self.tmp)
        result = crawl(["https://news.com/dup1", "https://news.com/dup2"], opts, fetcher=fetcher)

        oks = [a for a in result.articles if a.status == "ok"]
        self.assertEqual(len(oks), 1)
        self.assertEqual(result.status.duplicates, 1)

    def test_error_pages_recorded(self):
        fetcher = FakeFetcher()
        fetcher.add("https://news.com/err", "boom", status=500)
        opts = PipelineOptions(max_pages=5, max_depth=0, out_dir=self.tmp)
        result = crawl(["https://news.com/err"], opts, fetcher=fetcher)

        errors = [a for a in result.articles if a.status == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("500", errors[0].error)

    def test_same_domain_restriction(self):
        fetcher = FakeFetcher()
        fetcher.add(
            "https://news.com/home",
            '<a href="https://news.com/a">in</a>'
            '<a href="https://outside.com/other">out</a>',
        )
        fetcher.add("https://news.com/a", article_body("https://news.com/a", "A"))
        fetcher.add("https://outside.com/other", article_body("https://outside.com/other", "Out"))
        opts = PipelineOptions(max_pages=5, max_depth=2, same_domain=True, out_dir=self.tmp)
        result = crawl(["https://news.com/home"], opts, fetcher=fetcher)

        urls = [a.url for a in result.articles if a.status == "ok"]
        self.assertIn("https://news.com/a", urls)
        self.assertNotIn("https://outside.com/other", urls)


if __name__ == "__main__":
    unittest.main()