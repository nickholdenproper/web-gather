import unittest

from web_gather.blocks import BlockList
from web_gather.search import (
    parse_ddg,
    parse_feed,
    parse_marginalia,
    parse_mojeek,
    parse_reddit_json,
    search_web,
)

DDG_HTML = """
<html><body>
<div class="results">
  <div class="result">
    <a class="result__a" href="https://alpha.com/news/1">Alpha Story One</a>
    <a class="result__snippet" href="#">Alpha snippet about the goal topic</a>
  </div>
  <div class="result">
    <a class="result__a" href="//beta.com/story">Beta Story Two</a>
  </div>
</div>
</body></html>
"""

GOOGLENEWS_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Google News</title>
<item><title>Gamma Report</title><link>https://gamma.com/x</link>
<description>Gamma gives an update on the topic.</description></item>
<item><title>Delta Brief</title><link>https://delta.com/y</link></item>
</channel></rss>
"""

MOJEEK_HTML = """
<html><body><ul class="results">
<li><h2><a href="https://epsilon.com/a">Epsilon Title</a></h2><p class="s">Epsilon snippet text.</p></li>
<li><h2><a href="https://zeta.com/b">Zeta Title</a></h2></li>
</ul></body></html>
"""

MARGINALIA_HTML = """
<html><body><div class="search-result">
<div class="title"><a href="https://eta.com/p">Eta Page</a></div>
<p>Eta snippet about the goal.</p></div></body></html>
"""

REDDIT_JSON = """{
  "data": {"children": [
    {"data": {"title": "Theta thread", "url": "https://theta.com/t/1", "selftext": "theta self text"}},
    {"data": {"title": "No url ok story", "url": "", "selftext": "x"}}
  ]}
}
"""


def make_get(body_by_prefix):
    def get_body(url):
        for prefix, body in body_by_prefix.items():
            if url.startswith(prefix):
                return body
        return "<html></html>"

    return get_body


class ParserTest(unittest.TestCase):
    def test_parse_ddg(self):
        r = parse_ddg(DDG_HTML)
        self.assertEqual(len(r), 2)
        self.assertEqual(r[0].title, "Alpha Story One")
        self.assertEqual(r[0].url, "https://alpha.com/news/1")
        self.assertEqual(r[1].url, "https://beta.com/story")  # protocol-relative fixed
        self.assertEqual(r[0].position, 1)

    def test_parse_ddg_unwraps_redirect(self):
        from web_gather.search import _real_url

        ddg = (
            '<a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fgov.org%2Fa'
            "&rut=abc\">Real Target</a>"
        )
        r = parse_ddg(ddg)
        self.assertEqual(r[0].url, "https://gov.org/a")
        # plain links pass through unchanged
        self.assertEqual(_real_url("https://plain.org/x"), "https://plain.org/x")

    def test_parse_feed(self):
        r = parse_feed(GOOGLENEWS_RSS, "googlenews")
        self.assertEqual(len(r), 2)
        self.assertEqual(r[0].engine, "googlenews")
        self.assertIn("Gamma gives", r[0].snippet)

    def test_parse_mojeek(self):
        r = parse_mojeek(MOJEEK_HTML)
        self.assertEqual(len(r), 2)
        self.assertEqual(r[0].title, "Epsilon Title")
        self.assertEqual(r[1].title, "Zeta Title")

    def test_parse_marginalia(self):
        r = parse_marginalia(MARGINALIA_HTML)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0].url, "https://eta.com/p")

    def test_parse_reddit(self):
        r = parse_reddit_json(REDDIT_JSON)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0].title, "Theta thread")


class SearchWebTest(unittest.TestCase):
    def test_single_engine(self):
        get_body = make_get({
            "https://html.duckduckgo.com": DDG_HTML,
            "https://news.google.com": GOOGLENEWS_RSS,
        })
        r = search_web("goal topic", engine="ddg", get_body=get_body)
        self.assertEqual(len(r), 2)
        self.assertTrue(all(x.engine == "ddg" for x in r))

    def test_auto_merges_and_dedupes(self):
        get_body = make_get({
            "https://html.duckduckgo.com": DDG_HTML,
            "https://news.google.com": GOOGLENEWS_RSS,  # distinct domains, no overlap
            "https://www.bing.com": GOOGLENEWS_RSS,
        })
        r = search_web("goal topic", engine="auto", limit=10, get_body=get_body)
        # ddg (2) + googlenews (2) -> merge; later engines break once limit reached
        self.assertGreaterEqual(len(r), 4)
        urls = [x.url for x in r]
        self.assertEqual(len(urls), len(set(urls)))

    def test_blocklist_filters_results(self):
        block = BlockList(blocked=["alpha.com", "gamma.com"])
        get_body = make_get({"https://html.duckduckgo.com": DDG_HTML, "https://news.google.com": GOOGLENEWS_RSS})
        r = search_web("goal topic", engine="auto", limit=10, get_body=get_body, blocklist=block)
        urls = [x.url for x in r]
        self.assertNotIn("https://alpha.com/news/1", urls)
        self.assertNotIn("https://gamma.com/x", urls)

    def test_browser_engine_requires_session(self):
        from web_gather.search import search_web

        with self.assertRaises(RuntimeError):
            search_web("goal topic", engine="google")


if __name__ == "__main__":
    unittest.main()
