import unittest
from pathlib import Path

from src.parsers.article_parser import parse_case_markdown
from src.parsers.html_cleaner import clean_and_score_text
from src.pipeline.tasks import (
    aggregate_reports,
    extract_events_from_docs,
    load_example_documents,
    map_events_to_funds,
    parse_documents,
)


ROOT = Path(__file__).resolve().parents[1]


class PipelineQualityTests(unittest.TestCase):
    def test_example_metadata_is_loaded(self) -> None:
        case = parse_case_markdown(ROOT / "examples" / "gold_case.md")
        self.assertEqual(case["source_type"], "media")
        self.assertEqual(case["published_at"], "2026-03-19")

    def test_html_cleaner_filters_chrome_noise(self) -> None:
        text = (
            "网站地图 联系我们 用户反馈。"
            "2026-03-21 国家能源局发布电网改造公告并披露招标计划。"
            "推荐阅读 扫码下载。"
        )
        result = clean_and_score_text(text)
        self.assertGreaterEqual(result["chrome_lines_filtered"], 1)
        self.assertGreaterEqual(result["noise_lines_filtered"], 1)
        self.assertIn("国家能源局发布电网改造公告", result["clean_text"])

    def test_freshness_gating_and_report_policy(self) -> None:
        raw_docs = load_example_documents(ROOT / "examples")
        parsed_docs = parse_documents(raw_docs)
        events = extract_events_from_docs(parsed_docs, window_days=7)
        signals = map_events_to_funds(events, window_days=7)
        reports = aggregate_reports(signals, window_days=7)

        self.assertGreaterEqual(len(events), 3)
        self.assertTrue(any(e.is_stale for e in events))
        self.assertTrue(any(not e.is_stale for e in events))
        self.assertTrue(any(r.fund_code == "002963" for r in reports))


if __name__ == "__main__":
    unittest.main()

