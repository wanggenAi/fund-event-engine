import unittest

from src.pipeline.contracts import FundReport
from src.utils.report_quality import compute_source_stability_score, enrich_reports_with_quality


class ReportQualityTests(unittest.TestCase):
    def test_source_stability_score(self) -> None:
        stats = {"sources_attempted": 10, "sources_succeeded": 8, "pages_attempted": 20, "pages_succeeded": 15}
        score = compute_source_stability_score(stats)
        self.assertGreater(score, 0.7)
        self.assertLess(score, 0.9)

    def test_enrich_reports_with_quality(self) -> None:
        report = FundReport(
            fund_code="TEST01",
            fund_name="Test Fund",
            fund_type="thematic_equity",
            analysis_window="7d",
            recent_event_count=2,
            stale_event_count_filtered=0,
            noise_event_count_filtered=0,
            low_tier_event_count_filtered=0,
            proxy_event_count_main=1,
            proxy_event_share_main=0.5,
            direct_event_count_main=1,
            source_diversity_main=2,
            decision_readiness="中",
            decision_constraints=[],
            signal_summary={},
            direction_3d="中性",
            direction_2w="利好",
            direction_3m="利好",
            long_term_logic="不变",
            confidence=0.7,
            conclusion_strength="中",
            warnings=[],
        )
        meta = enrich_reports_with_quality([report], collect_stats={"sources_attempted": 5, "sources_succeeded": 5}, history_path="outputs/history/test_history.json")
        self.assertIn("source_stability_score", meta)
        self.assertGreaterEqual(report.reference_value_score, 0.0)
        self.assertLessEqual(report.reference_value_score, 1.0)


if __name__ == "__main__":
    unittest.main()

