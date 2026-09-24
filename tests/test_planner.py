import unittest

from web_gather.planner import plan_queries


class FakeLLM:
    def __init__(self, text):
        self.text = text

    def complete(self, messages):
        return self.text


class PlannerTest(unittest.TestCase):
    def test_heuristic_returns_queries(self):
        q = plan_queries("What are the main health risks of ultra-processed foods")
        self.assertGreaterEqual(len(q), 3)
        self.assertLessEqual(len(q), 4)
        self.assertIn("ultra-processed foods", " ".join(q))  # keywords preserved

    def test_empty_goal(self):
        self.assertEqual(plan_queries(""), [])
        self.assertEqual(plan_queries("   "), [])

    def test_n_respected(self):
        q = plan_queries("latest AI regulation news in europe", n=2)
        self.assertEqual(len(q), 2)

    def test_llm_path_wins(self):
        llm = FakeLLM("one query\n1. first query\n2. second query")
        q = plan_queries("goal here", n=2, llm=llm)
        self.assertEqual(q, ["one query", "first query"])
        self.assertEqual(len(q), 2)

    def test_llm_failure_falls_back(self):
        class Boom:
            def complete(self, messages):
                raise RuntimeError("offline")

        q = plan_queries("some research goal for testing", n=3, llm=Boom())
        self.assertGreaterEqual(len(q), 3)


if __name__ == "__main__":
    unittest.main()