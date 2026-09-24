import unittest

from web_gather.browser import HybridFetcher, _unwrap_google, looks_like_js_shell
from web_gather.fetch import FetchResult

from fake_fetcher import FakeFetcher


class JsShellTest(unittest.TestCase):
    def test_detects_shell(self):
        self.assertTrue(looks_like_js_shell('<html><body><div id="root"></div></body></html>'))
        self.assertTrue(looks_like_js_shell('<script src="/app.js"></script>'))

    def test_plain_html_not_shell(self):
        self.assertFalse(looks_like_js_shell("<html><body><p>Real prose paragraph here.</p></body></html>"))


class UnwrapTest(unittest.TestCase):
    def test_unwrap_google(self):
        self.assertEqual(_unwrap_google("/url?q=https://real.com/x&sa=U"), "https://real.com/x")
        self.assertEqual(_unwrap_google("https://www.google.com/other"), None)
        self.assertEqual(_unwrap_google("https://real.com/direct"), "https://real.com/direct")


class HybridFetcherTest(unittest.TestCase):
    class FakeBrowser:
        def __init__(self):
            self.calls = []

        def available(self):
            return True

        def get(self, url):
            self.calls.append(url)
            return FetchResult(url=url, status_code=200, headers={}, text="<html><body>rendered</body></html>")

    def test_never_uses_http_only(self):
        http = FakeFetcher()
        http.add("https://x.com/a", "<html><body><p>content</p></body></html>")
        browser = self.FakeBrowser()
        hy = HybridFetcher(http, browser, "never")
        r = hy.get("https://x.com/a")
        self.assertEqual(r.text, "<html><body><p>content</p></body></html>")
        self.assertEqual(browser.calls, [])

    def test_no_browser_falls_back_to_http(self):
        http = FakeFetcher()
        http.add("https://x.com/a", "<html><body><p>content</p></body></html>")
        hy = HybridFetcher(http, None, "auto")
        r = hy.get("https://x.com/a")
        self.assertEqual(r.status_code, 200)

    def test_auto_promotes_for_js_shell(self):
        http = FakeFetcher()
        http.add("https://x.com/spa", '<html><body><div id="root"></div></body></html>')
        browser = self.FakeBrowser()
        hy = HybridFetcher(http, browser, "auto")
        r = hy.get("https://x.com/spa")
        self.assertEqual(r.url, "https://x.com/spa")
        self.assertEqual(browser.calls, ["https://x.com/spa"])

    def test_auto_promotes_for_http_error(self):
        http = FakeFetcher()
        http.add("https://x.com/err", "<html>boom</html>", status=503)
        browser = self.FakeBrowser()
        hy = HybridFetcher(http, browser, "auto")
        r = hy.get("https://x.com/err")
        self.assertEqual(browser.calls, ["https://x.com/err"])

    def test_always_requires_browser(self):
        from web_gather.browser import BrowserError

        http = FakeFetcher()
        hy = HybridFetcher(http, None, "always")
        with self.assertRaises(BrowserError):
            hy.get("https://x.com/a")


if __name__ == "__main__":
    unittest.main()