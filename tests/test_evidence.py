import json
import tempfile
import unittest
from pathlib import Path

from web_gather.evidence import EvidenceItem, clean_snippet, extract_findings, write_findings

GOAL = "how much exercise do adults need per week"

TEXT = """
Public health bodies say adults should get at least 150 minutes of
moderate-intensity aerobic activity per week. That recommendation comes from
a review of dozens of long-running observational studies tracking adults over
many years.

Another report from a leading university recommends two days of strength
training alongside the aerobic baseline. Researchers noted that surpassing
300 minutes per week gave diminishing returns for most adults.

This paragraph is pure filler with no relation to the research goal,
discussing the weather in a distant country and the price of coffee beans.
It exists only to check that irrelevant prose is not returned as evidence.
"""


class BadQuoteLLM:
    def complete(self, messages):
        return '{"finding": "150 minutes per week", "quote": "adults should get at least 150 minutes", "confidence": 0.8}'
        # single-line JSON so the line-parse succeeds


class ExtractTest(unittest.TestCase):
    def test_heuristic_keeps_goal_relevant(self):
        items = extract_findings(GOAL, TEXT, max_findings=3)
        self.assertGreaterEqual(len(items), 1)
        for item in items:
            self.assertTrue(item.finding)
            self.assertIn("minutes", item.quote.lower())
            self.assertTrue(0 <= item.confidence <= 1)

    def test_empty_text(self):
        self.assertEqual(extract_findings(GOAL, ""), [])

    def test_llm_path_shapes_items(self):
        items = extract_findings(GOAL, TEXT, llm=BadQuoteLLM(), max_findings=1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].finding, "150 minutes per week")
        self.assertIn("150 minutes", items[0].quote)
        self.assertEqual(items[0].confidence, 0.8)


class CleanSnippetTest(unittest.TestCase):
    def test_strips_markdown_and_tables(self):
        dirty = "| Elon Musk |\n| --- |\n\nHe is known for [Tesla and SpaceX](https://x.com). See https://wiki.org"
        clean = clean_snippet(dirty)
        self.assertNotIn("|", clean)
        self.assertNotIn("http", clean)
        self.assertIn("Tesla and SpaceX", clean)

    def test_cuts_at_sentence_boundary(self):
        long = "Elon Musk is the founder of SpaceX and a senior advisor. This trailing filler sentence should be trimmed away completely."
        clean = clean_snippet(long)
        self.assertIn("Elon Musk is the founder", clean)
        self.assertIn("advisor", clean)
        self.assertNotIn("trailing filler", clean)

    def test_short_passthrough(self):
        self.assertEqual(clean_snippet("short answer ok"), "short answer ok")


class WriteTest(unittest.TestCase):
    def test_writes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            items = [
                EvidenceItem(
                    finding="150 minutes per week",
                    source_url="https://gov.org/a",
                    page_title="Guidelines",
                    quote="adults should get 150 minutes per week",
                    confidence=0.8,
                )
            ]
            written = write_findings(out, items, {"goal": GOAL})
            self.assertIn(out / "findings.json", written)
            self.assertIn(out / "findings.md", written)
            payload = json.loads((out / "findings.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["findings"][0]["source_url"], "https://gov.org/a")
            md = (out / "findings.md").read_text(encoding="utf-8")
            self.assertIn(GOAL, md)
            self.assertIn("150 minutes", md)


if __name__ == "__main__":
    unittest.main()