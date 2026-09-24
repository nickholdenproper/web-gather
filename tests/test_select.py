import unittest

from web_gather.search import SearchResult
from web_gather.select import select_sites

GOAL = "how much exercise do adults need per week"


def result(engine, url, title, position=1, snippet=""):
    return SearchResult(engine=engine, title=title, url=url, snippet=snippet, position=position)


class SelectTest(unittest.TestCase):
    def test_cross_engine_agreement_ranks_first(self):
        results = [
            result("ddg", "https://gov.org/activity", "Physical Activity Guidelines", 1),
            result("googlenews", "https://gov.org/activity", "Physical Activity Guidelines", 3),
        ]
        selected = select_sites(results, GOAL)
        self.assertEqual(len(selected), 1)
        site = selected[0]
        self.assertEqual(site.engines, ["ddg", "googlenews"])
        self.assertGreater(site.score, 50)

    def test_goal_relevance_boost(self):
        results = [
            result("ddg", "https://random.com/x", "Random unrelated homepage", 1),
            result("ddg", "https://gov.org/exercise-adults", "Adults exercise weekly minutes needed", 1, snippet="adults need exercise weekly"),
        ]
        selected = select_sites(results, GOAL)
        self.assertEqual(selected[0].url, "https://gov.org/exercise-adults")

    def test_junk_penalty(self):
        results = [
            result("ddg", "https://top10.click/list", "Top Ten Sponsored", 1),
            result("ddg", "https://ok.org/solid", "Solid Article About Adults", 1),
        ]
        selected = select_sites(results, GOAL)
        self.assertEqual(selected[0].url, "https://ok.org/solid")

    def test_min_score_and_limit(self):
        results = [result("ddg", "https://a.org/%d" % i, "Some Title Here %d" % i, 1) for i in range(10)]
        selected = select_sites(results, GOAL, min_score=0, max_sites=3)
        self.assertLessEqual(len(selected), 3)
        filtered = select_sites(results, GOAL, min_score=999)
        self.assertEqual(filtered, [])

    def test_empty_results(self):
        self.assertEqual(select_sites([], GOAL), [])


if __name__ == "__main__":
    unittest.main()