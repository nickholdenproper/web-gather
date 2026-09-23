import unittest
from pathlib import Path

from web_gather.models import Article, CrawlStatus
from web_gather.output import write_outputs


class OutputTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__file__).parent / "_tmp_out"
        if self.tmp.exists():
            import shutil

            shutil.rmtree(self.tmp)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_writes_index_json_md_corpus(self):
        articles = [
            Article(
                url="https://news.com/a",
                domain="news.com",
                title="Story A",
                summary="Sum.",
                text="Body text of story A.",
                body_md="Body text of story A.",
            ),
            Article(
                url="https://news.com/b",
                domain="news.com",
                status="error",
                error="HTTP 500",
            ),
        ]
        status = CrawlStatus(visited=2, ok=1, errors=1)
        written = write_outputs(self.tmp, articles, status, {"max_pages": 50})

        names = sorted(p.name for p in written)
        self.assertIn("index.json", names)
        self.assertIn("corpus.txt", names)
        self.assertTrue(any(n.endswith(".json") and n.startswith("0001-") for n in names))
        self.assertTrue(any(n.endswith(".md") for n in names))

        corpus = (self.tmp / "corpus.txt").read_text(encoding="utf-8")
        self.assertIn("<article>", corpus)
        self.assertIn("Body text of story A.", corpus)
        self.assertNotIn("HTTP 500", corpus)

        index = (self.tmp / "index.json").read_text(encoding="utf-8")
        self.assertIn('"visited": 2', index)


if __name__ == "__main__":
    unittest.main()