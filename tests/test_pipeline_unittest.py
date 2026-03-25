import unittest
from pathlib import Path

from src.parsers.article_parser import parse_case_markdown
from src.parsers.html_cleaner import clean_and_score_text
from src.pipeline.tasks import (
    _source_feedback_multiplier,
    aggregate_reports,
    extract_events_from_docs,
    load_example_documents,
    map_events_to_funds,
    parse_documents,
    set_runtime_scoring_override,
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


class NegationDetectionTests(unittest.TestCase):
    def test_negation_flips_positive_to_bearish(self) -> None:
        from src.event_engine.event_extractor import _direction_hint
        # "不会上涨" should yield bearish, not bullish
        result = _direction_hint("黄金不会上涨，市场预期趋于悲观")
        self.assertEqual(result, "利空")

    def test_negation_flips_negative_to_bullish(self) -> None:
        from src.event_engine.event_extractor import _direction_hint
        result = _direction_hint("稀土价格并非下跌，供需仍然偏紧")
        self.assertEqual(result, "利好")

    def test_plain_positive_unchanged(self) -> None:
        from src.event_engine.event_extractor import _direction_hint
        result = _direction_hint("电网投资显著增长，招标大幅超预期")
        self.assertEqual(result, "利好")


class SourceFeedbackBlendTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_runtime_scoring_override({})

    def test_prior_and_posterior_blend(self) -> None:
        set_runtime_scoring_override(
            {
                "source_feedback": {
                    "enabled": True,
                    "min_multiplier": 0.8,
                    "max_multiplier": 1.2,
                    "prior_multiplier_default": 1.0,
                    "prior_multiplier_by_source_tier": {"A": 1.05, "B": 1.0},
                    "posterior_blend_weight": 0.5,
                    "source_multiplier_by_name": {"SRC": 0.9},
                }
            }
        )
        m = _source_feedback_multiplier(
            "SRC",
            fund_type="thematic_equity",
            feedback_horizon="2w",
            source_tier="A",
            source_category="authoritative_data",
        )
        # blend(1.05, 0.9, w=0.5) = 0.975
        self.assertAlmostEqual(m, 0.975, places=6)


if __name__ == "__main__":
    unittest.main()
