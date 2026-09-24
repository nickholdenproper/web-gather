import unittest

from web_gather.tools import TOOLS, call_tool


class ToolsTest(unittest.TestCase):
    def test_registry_lists_four_tools(self):
        names = [t["name"] for t in TOOLS]
        self.assertEqual(
            names, ["web_search", "fetch_url", "crawl", "research"]
        )
        for t in TOOLS:
            self.assertIn("schema", t)
            self.assertIn("properties", t["schema"])
            self.assertIn("required", t["schema"])

    def test_unknown_tool_raises(self):
        with self.assertRaises(KeyError):
            call_tool("nope", {})


if __name__ == "__main__":
    unittest.main()