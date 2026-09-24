import tempfile
import unittest
from pathlib import Path

from web_gather.research import ResearchOptions, research

from fake_fetcher import FakeFetcher

GOAL = "how much exercise do adults need per week"

DDG_HTML = """
<html><body><div class="results">
<div class="result"><a class="result__a" href="https://gov.org/activity">Gov Exercise Guidelines</a></div>
<div class="result"><a class="result__a" href="https://uni.org/study">University Study</a></div>
<div class="result"><a class="result__a" href="https://junk.example/x">Junk Sponsored Link Farm</a></div>
</div></body></html>
"""

PAGE = {
    "https://gov.org/activity": """<html><head><title>Guidelines</title></head><body>
      <h1>Guidelines</h1>
      <p>Health experts recommend that adults get at least 150 minutes of
      moderate-intensity exercise per week for good cardiovascular health.
      That recommendation is based on long-term studies following adults.</p>
      <p>Another finding suggests adults who exceed 300 minutes per week gain
      only marginal additional benefits. Individual needs vary though.</p>
      </body></html>""",
    "https://uni.org/study": """<html><head><title>University Study</title></head><body>
      <p>Researchers tracked adults over twelve years and found that the weekly
      exercise dose matters more than the type. Adults meeting 150 minutes per
      week reported the strongest health outcomes in the cohort.</p>
      <p>This study confirms the mainstream guidance that adults need regular
      moderate exercise every week for lasting benefits.</p>
      </body></html>""",
}


def make_get():
    def get_body(url):
        if url.startswith("https://html.duckduckgo.com"):
            return DDG_HTML
        return ""

    return get_body


class ResearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, browser_mode="never"):
        fetcher = FakeFetcher()
        for url, body in PAGE.items():
            fetcher.add(url, body)
        opts = ResearchOptions(
            goal=GOAL,
            engine="ddg",
            max_queries=1,
            max_sites=2,
            min_score=0,
            max_findings_per_site=2,
            browser_mode=browser_mode,
            out_dir=self.tmp,
        )
        return research(GOAL, opts, get_body=make_get(), http_fetcher=fetcher)

    def test_heuristic_end_to_end(self):
        result = self._run()
        self.assertTrue(result.queries)
        self.assertGreaterEqual(len(result.selected), 2)
        self.assertGreaterEqual(len(result.findings), 1)
        for f in result.findings:
            self.assertTrue(f.quote)
            self.assertTrue(f.source_url)
            self.assertTrue(f.finding)

    def test_findings_written(self):
        result = self._run()
        self.assertTrue((self.tmp / "findings.json").exists())
        self.assertTrue((self.tmp / "findings.md").exists())

    def test_browser_mode_never_still_works(self):
        result = self._run(browser_mode="never")
        self.assertGreaterEqual(len(result.findings), 1)

    def test_empty_results_ok(self):
        fetcher = FakeFetcher()
        opts = ResearchOptions(
            goal="zzz nonexistent goal phrase",
            engine="ddg",
            max_queries=1,
            max_sites=1,
            min_score=0,
            browser_mode="never",
            out_dir=self.tmp,
        )
        result = research("zzz nonexistent goal phrase", opts, get_body=lambda url: "", http_fetcher=fetcher)
        self.assertEqual(result.findings, [])
        self.assertTrue((self.tmp / "findings.json").exists())


if __name__ == "__main__":
    unittest.main()