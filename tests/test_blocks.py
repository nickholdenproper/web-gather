import tempfile
import unittest
from pathlib import Path

from web_gather.blocks import BlockList


class BlockListTest(unittest.TestCase):
    def test_blocked_domain_prefix(self):
        block = BlockList(blocked=["evil.com", "ads.example.org"])
        self.assertTrue(block.blocks("https://evil.com/post/1"))
        self.assertTrue(block.blocks("https://www.evil.com/x"))
        self.assertTrue(block.blocks("http://ads.example.org/b"))

    def test_blocked_glob(self):
        block = BlockList(blocked=["*.tracked.net"])
        self.assertTrue(block.blocks("https://sub.tracked.net/page"))

    def test_allowed_only(self):
        block = BlockList(allowed=["good.com"])
        self.assertFalse(block.blocks("https://good.com/a"))
        self.assertTrue(block.blocks("https://bad.com/a"))
        self.assertTrue(block.blocks("https://other.com/a"))

    def test_free_by_default(self):
        block = BlockList()
        self.assertFalse(block.blocks("https://anything.com/x"))
        self.assertFalse(block.blocks("mailto:x@y.com"))
        self.assertFalse(block.blocks("file:///tmp"))

    def test_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "block.txt"
            p.write_text("# comment\n\nevil.com\n*.tracked.net\n", encoding="utf-8")
            block = BlockList.from_file(p)
            self.assertTrue(block.blocks("https://evil.com/z"))
            self.assertTrue(block.blocks("https://a.tracked.net/q"))
            self.assertFalse(block.blocks("https://fine.com/q"))


if __name__ == "__main__":
    unittest.main()