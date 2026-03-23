import unittest
from unittest.mock import patch

from src.collectors.source_collector import collect_documents_from_sources


class CollectorTests(unittest.TestCase):
    @patch("src.collectors.source_collector._fetch_url", side_effect=RuntimeError("network down"))
    def test_collect_respects_max_sources_even_on_fail(self, _mock_fetch) -> None:
        docs, stats = collect_documents_from_sources(max_sources=2, max_items_per_source=1)
        self.assertLessEqual(len(docs), 2)
        self.assertTrue(all("collect_failed" in d.title for d in docs))
        self.assertEqual(stats.sources_attempted, 2)

    @patch("src.collectors.source_collector._fetch_url", side_effect=RuntimeError("network down"))
    def test_collect_strict_mode_raises(self, _mock_fetch) -> None:
        with self.assertRaises(RuntimeError):
            collect_documents_from_sources(max_sources=1, max_items_per_source=1, strict=True)


if __name__ == "__main__":
    unittest.main()
