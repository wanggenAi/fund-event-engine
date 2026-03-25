import unittest
from datetime import datetime, timedelta, timezone

from src.utils.source_feedback import build_source_feedback


class SourceFeedbackTests(unittest.TestCase):
    def test_build_source_feedback(self) -> None:
        prediction_rows = [
            {"fund_code": "011035", "asof_date": "2026-03-01", "key_event_sources": ["S1", "S2"]},
            {"fund_code": "011035", "asof_date": "2026-03-02", "key_event_sources": ["S1"]},
        ]
        eval_details = [
            {"fund_code": "011035", "asof_date": "2026-03-01", "status": "ok", "matched": True},
            {"fund_code": "011035", "asof_date": "2026-03-02", "status": "ok", "matched": False},
            {"fund_code": "011035", "asof_date": "2026-03-03", "status": "insufficient_future_nav", "matched": False},
        ]
        out = build_source_feedback(
            prediction_rows=prediction_rows,
            eval_details=eval_details,
            min_samples=1,
            min_samples_floor=1,
            enable_dynamic_min_samples=False,
            sensitivity=0.4,
            half_life_days=9999,
            decay_floor=1.0,
            min_multiplier=0.9,
            max_multiplier=1.1,
        )
        self.assertIn("source_multipliers", out)
        self.assertIn("S1", out["source_multipliers"])
        self.assertIn("S2", out["source_multipliers"])
        self.assertGreaterEqual(out["source_multipliers"]["S1"], 0.9)
        self.assertLessEqual(out["source_multipliers"]["S1"], 1.1)
        self.assertIn("source_multipliers_by_fund_type", out)
        self.assertIn("source_multipliers_by_horizon", out)
        self.assertIn("source_multipliers_by_fund_type_horizon", out)

    def test_build_source_feedback_by_fund_type(self) -> None:
        prediction_rows = [
            {"fund_code": "011035", "asof_date": "2026-03-01", "fund_type": "thematic_equity", "key_event_sources": ["SX"]},
            {"fund_code": "002963", "asof_date": "2026-03-01", "fund_type": "gold", "key_event_sources": ["SX"]},
        ]
        eval_details = [
            {"fund_code": "011035", "asof_date": "2026-03-01", "status": "ok", "matched": True},
            {"fund_code": "002963", "asof_date": "2026-03-01", "status": "ok", "matched": False},
        ]
        out = build_source_feedback(
            prediction_rows=prediction_rows,
            eval_details=eval_details,
            min_samples=1,
            min_samples_floor=1,
            enable_dynamic_min_samples=False,
            sensitivity=0.6,
            half_life_days=9999,
            decay_floor=1.0,
            min_multiplier=0.85,
            max_multiplier=1.15,
        )
        by_ft = out["source_multipliers_by_fund_type"]
        self.assertIn("thematic_equity", by_ft)
        self.assertIn("gold", by_ft)
        self.assertIn("SX", by_ft["thematic_equity"])
        self.assertIn("SX", by_ft["gold"])
        self.assertGreater(by_ft["thematic_equity"]["SX"], by_ft["gold"]["SX"])

    def test_time_decay_prefers_recent_samples(self) -> None:
        old_day = (datetime.now(timezone.utc) - timedelta(days=200)).strftime("%Y-%m-%d")
        new_day = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        prediction_rows = [
            {"fund_code": "011035", "asof_date": old_day, "fund_type": "thematic_equity", "key_event_sources": ["SREC"]},
            {"fund_code": "011035", "asof_date": new_day, "fund_type": "thematic_equity", "key_event_sources": ["SREC"]},
        ]
        eval_details = [
            {"fund_code": "011035", "asof_date": old_day, "status": "ok", "matched": False},
            {"fund_code": "011035", "asof_date": new_day, "status": "ok", "matched": True},
        ]
        out = build_source_feedback(
            prediction_rows=prediction_rows,
            eval_details=eval_details,
            min_samples=2,
            min_samples_floor=1,
            enable_dynamic_min_samples=True,
            sensitivity=0.6,
            half_life_days=30,
            decay_floor=0.2,
            min_multiplier=0.85,
            max_multiplier=1.15,
        )
        self.assertIn("SREC", out["source_multipliers"])
        self.assertGreater(out["source_multipliers"]["SREC"], 1.0)

    def test_uncertainty_shrinkage_reduces_extreme_multiplier(self) -> None:
        prediction_rows = [
            {"fund_code": "011035", "asof_date": "2026-03-10", "fund_type": "thematic_equity", "key_event_sources": ["SLOW"]},
        ]
        eval_details = [
            {"fund_code": "011035", "asof_date": "2026-03-10", "status": "ok", "matched": True},
        ]
        no_shrink = build_source_feedback(
            prediction_rows=prediction_rows,
            eval_details=eval_details,
            min_samples=1,
            min_samples_floor=1,
            enable_dynamic_min_samples=False,
            sensitivity=0.8,
            half_life_days=9999,
            decay_floor=1.0,
            enable_uncertainty_shrinkage=False,
            shrinkage_strength=6.0,
            min_multiplier=0.85,
            max_multiplier=1.15,
        )
        shrink = build_source_feedback(
            prediction_rows=prediction_rows,
            eval_details=eval_details,
            min_samples=1,
            min_samples_floor=1,
            enable_dynamic_min_samples=False,
            sensitivity=0.8,
            half_life_days=9999,
            decay_floor=1.0,
            enable_uncertainty_shrinkage=True,
            shrinkage_strength=6.0,
            min_multiplier=0.85,
            max_multiplier=1.15,
        )
        self.assertIn("SLOW", no_shrink["source_multipliers"])
        self.assertIn("SLOW", shrink["source_multipliers"])
        self.assertGreater(no_shrink["source_multipliers"]["SLOW"], shrink["source_multipliers"]["SLOW"])


if __name__ == "__main__":
    unittest.main()
