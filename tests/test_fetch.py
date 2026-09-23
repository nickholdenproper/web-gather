import unittest
from unittest.mock import patch

from web_gather.fetch import FetchResult, Fetcher


class FetcherTest(unittest.TestCase):
    def test_returns_fetch_result(self):
        fetcher = Fetcher(delay=0, retries=0)
        with patch.object(fetcher, "_httpx_get", return_value=FetchResult("https://x.com/p", 200, {}, "<p>hi</p>")):
            result = fetcher.get("https://x.com/p")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.text, "<p>hi</p>")

    def test_robots_blocked_disallows(self):
        from urllib import robotparser

        fetcher = Fetcher(delay=0, retries=0, ignore_robots=False)
        fake_rp = robotparser.RobotFileParser()
        fake_rp.parse(["User-agent: *", "Disallow: /"])
        with patch.object(fetcher, "_robots_cache", {"blocked.example.com": fake_rp}):
            self.assertFalse(fetcher._allowed("https://blocked.example.com/p"))

    def test_robots_allowed(self):
        from urllib import robotparser

        fetcher = Fetcher(delay=0, retries=0, ignore_robots=False)
        fake_rp = robotparser.RobotFileParser()
        fake_rp.parse(["User-agent: *", "Allow: /"])
        with patch.object(fetcher, "_robots_cache", {"x.com": fake_rp}):
            self.assertTrue(fetcher._allowed("https://x.com/p"))

    def test_ignore_robots_allows(self):
        fetcher = Fetcher(delay=0, retries=0, ignore_robots=True)
        self.assertTrue(fetcher._allowed("https://x.com/anything"))

    def test_no_robots_file_is_allow(self):
        fetcher = Fetcher(delay=0, retries=0)
        with patch.object(fetcher, "_load_robots", return_value=None):
            self.assertTrue(fetcher._allowed("https://x.com/p"))

    def test_retries_then_success(self):
        fetcher = Fetcher(delay=0, retries=2)
        calls = {"n": 0}

        def flaky(url):
            calls["n"] += 1
            if calls["n"] < 3:
                raise IOError("network hiccup")
            return FetchResult(url, 200, {}, "<p>ok</p>")

        with patch.object(fetcher, "_httpx_get", side_effect=flaky):
            result = fetcher.get("https://x.com/p")
        self.assertEqual(result.text, "<p>ok</p>")
        self.assertEqual(calls["n"], 3)

    def test_robot_cache_loads_once(self):
        fetcher = Fetcher(delay=0, retries=0)
        with patch.object(fetcher, "_load_robots", return_value=None) as load:
            fetcher._robots("x.com")
            fetcher._robots("x.com")
        load.assert_called_once()

    def test_robots_tolerates_network_errors(self):
        fetcher = Fetcher(delay=0, retries=0)
        with patch.object(fetcher, "_httpx_get", side_effect=OSError("network down")):
            self.assertIsNone(fetcher._load_robots("down.example.com"))
            self.assertIsNone(fetcher._robots("down.example.com"))


if __name__ == "__main__":
    unittest.main()