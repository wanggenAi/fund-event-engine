import unittest

from src.pipeline.contracts import FundReport
from src.utils.report_quality import enrich_reports_with_quality


class HighReadinessGateTests(unittest.TestCase):
    def test_high_readiness_is_downgraded_when_proxy_too_high(self):
        report = FundReport(
            fund_code="x",
            fund_name="demo",
            fund_type="thematic_equity",
            analysis_window="7d",
            recent_event_count=3,
            stale_event_count_filtered=0,
            noise_event_count_filtered=0,
            low_tier_event_count_filtered=0,
            proxy_event_count_main=2,
            proxy_event_share_main=0.67,
            direct_event_count_main=2,
            source_diversity_main=2,
            decision_readiness="高",
            decision_constraints=[],
            signal_summary={},
            direction_3d="利好",
            direction_2w="利好",
            direction_3m="利好",
            long_term_logic="强化",
            confidence=0.8,
            conclusion_strength="高",
            warnings=[],
        )
        enrich_reports_with_quality([report], {"sources_attempted": 10, "sources_succeeded": 9, "pages_attempted": 10, "pages_succeeded": 10}, history_path="/tmp/fund_event_engine_test_history2.json")
        self.assertEqual(report.decision_readiness, "中")
        self.assertIn("high_readiness_blocked_by_proxy_share", report.quality_flags)


if __name__ == "__main__":
    unittest.main()
