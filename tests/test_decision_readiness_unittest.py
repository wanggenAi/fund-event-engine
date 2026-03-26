import unittest

from src.pipeline.contracts import FundReport
from src.utils.report_quality import enrich_reports_with_quality
from src.pipeline.tasks import _decision_readiness


class DecisionReadinessTests(unittest.TestCase):
    def test_decision_readiness_low_when_severe_constraints(self):
        self.assertEqual(_decision_readiness("高", ["proxy_dominant"]), "低")
        self.assertEqual(_decision_readiness("中", ["single_source_main_evidence"]), "低")

    def test_decision_readiness_medium_when_only_moderate_constraints(self):
        self.assertEqual(_decision_readiness("高", ["low_source_diversity"]), "中")

    def test_quality_flags_include_proxy_dominance(self):
        report = FundReport(
            fund_code="x",
            fund_name="demo",
            fund_type="gold",
            analysis_window="7d",
            recent_event_count=2,
            stale_event_count_filtered=0,
            noise_event_count_filtered=0,
            low_tier_event_count_filtered=0,
            proxy_event_count_main=2,
            proxy_event_share_main=1.0,
            direct_event_count_main=0,
            source_diversity_main=1,
            decision_readiness="低",
            decision_constraints=["proxy_dominant", "single_source_main_evidence"],
            signal_summary={},
            direction_3d="利空",
            direction_2w="利空",
            direction_3m="利空",
            long_term_logic="弱化",
            confidence=0.6,
            conclusion_strength="低",
            warnings=[],
        )
        enrich_reports_with_quality([report], {"sources_attempted": 10, "sources_succeeded": 8, "pages_attempted": 10, "pages_succeeded": 10}, history_path="/tmp/fund_event_engine_test_history.json")
        self.assertIn("single_source_dominance", report.quality_flags)
        self.assertIn("proxy_dominant_without_direct_confirmation", report.quality_flags)
        self.assertIn("decision_readiness_low", report.quality_flags)


if __name__ == "__main__":
    unittest.main()
