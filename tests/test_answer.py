import unittest
from unittest import mock

from web_gather.answer import AskOptions, AnswerResult, _paragraph_heuristic, ask
from web_gather.evidence import EvidenceItem
from web_gather.research import ResearchResult
from web_gather.select import SelectedSite


def fake_research(question, opts=None, llm=None, get_body=None, http_fetcher=None, browser=None):
    return ResearchResult(
        goal=question,
        queries=["q1"],
        selected=[
            SelectedSite(url="https://gov.org/a", title="Gov Guidelines",
                         snippet="", score=80, engines=["ddg"], positions=[1]),
            SelectedSite(url="https://uni.org/b", title="Uni Study",
                         snippet="", score=60, engines=["ddg"], positions=[2]),
        ],
        findings=[
            EvidenceItem(finding="Adults need 150 minutes per week",
                         source_url="https://gov.org/a", page_title="Gov Guidelines",
                         quote="adults need 150 minutes", confidence=0.9),
            EvidenceItem(finding="Strength training twice weekly is recommended",
                         source_url="https://uni.org/b", page_title="Uni Study",
                         quote="two days of strength training", confidence=0.7),
        ],
    )


class FakeLLM:
    def __init__(self, text):
        self.text = text

    def complete(self, messages):
        assert any("Question:" in m["content"] for m in messages)
        return self.text


class AskTest(unittest.TestCase):
    @mock.patch("web_gather.answer.run_research", side_effect=fake_research)
    def test_ask_llm_paragraph(self, _m):
        llm = FakeLLM("Adults should aim for 150 minutes per week [1].")
        r = ask("how much exercise do adults need?", AskOptions(), llm=llm)
        self.assertIsInstance(r, AnswerResult)
        self.assertTrue(r.used_llm)
        self.assertEqual(r.paragraph, "Adults should aim for 150 minutes per week [1].")
        self.assertEqual(len(r.sources), 2)
        self.assertEqual(len(r.findings), 2)

    @mock.patch("web_gather.answer.run_research", side_effect=fake_research)
    def test_ask_compiled_paragraph_without_llm(self, _m):
        r = ask("how much exercise do adults need?", AskOptions(), llm=None)
        self.assertFalse(r.used_llm)
        self.assertIn("150 minutes", r.paragraph)
        self.assertIn("gov.org", r.paragraph)

    @mock.patch("web_gather.answer.run_research", side_effect=fake_research)
    def test_llm_failure_falls_back(self, _m):
        class Boom:
            def complete(self, messages):
                raise RuntimeError("offline")

        r = ask("how much exercise do adults need?", AskOptions(), llm=Boom())
        self.assertFalse(r.used_llm)
        self.assertIn("150 minutes", r.paragraph)


class HeuristicParagraphTest(unittest.TestCase):
    def test_no_findings(self):
        text = _paragraph_heuristic("q?", [], [])
        self.assertIn("no clear", text)

    def test_findings_compiled(self):
        items = [
            EvidenceItem(finding="A claim about adults",
                         source_url="https://gov.org/x", quote="quote a", confidence=0.9)
        ]
        selected = [SelectedSite("https://gov.org/x", "T", "", 70, ["ddg"], [1])]
        text = _paragraph_heuristic("how much exercise do adults need", items, selected)
        self.assertIn("A claim about adults", text)
        self.assertIn("gov.org", text)


if __name__ == "__main__":
    unittest.main()