import unittest

from web_gather.dedupe import content_fingerprint, normalize_url


class NormalizeUrlTest(unittest.TestCase):
    def test_tracking_params_stripped(self):
        url = "https://Example.COM/a/b?utm_source=x&id=5&ref=y"
        self.assertEqual(normalize_url(url), "https://example.com/a/b?id=5")

    def test_www_dropped_lowercased(self):
        self.assertEqual(
            normalize_url("https://www.News.com/story/"), "https://news.com/story"
        )

    def test_default_port_and_fragment(self):
        self.assertEqual(
            normalize_url("http://site.com:80/x#top"), "http://site.com/x"
        )

    def test_https_default_port_kept(self):
        self.assertEqual(
            normalize_url("https://site.com:443/x"), "https://site.com/x"
        )

    def test_scheme_missing_defaults_http(self):
        self.assertEqual(normalize_url("example.com/x"), "http://example.com/x")


class FingerprintTest(unittest.TestCase):
    def test_whitespace_insensitive(self):
        self.assertEqual(
            content_fingerprint("Hello  world\n today"),
            content_fingerprint(" Hello world today "),
        )

    def test_differing_text_different_hash(self):
        self.assertNotEqual(
            content_fingerprint("one story here"),
            content_fingerprint("a totally different story"),
        )

    def test_empty_gives_none(self):
        self.assertIsNone(content_fingerprint("   "))


if __name__ == "__main__":
    unittest.main()