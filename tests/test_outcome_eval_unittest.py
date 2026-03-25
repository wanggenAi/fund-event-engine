import unittest

from src.utils.outcome_eval import classify_return_direction, evaluate_prediction_rows, realized_direction_from_series


class OutcomeEvalTests(unittest.TestCase):
    def test_classify_return_direction(self) -> None:
        self.assertEqual(classify_return_direction(0.01, 0.002), "利好")
        self.assertEqual(classify_return_direction(-0.01, 0.002), "利空")
        self.assertEqual(classify_return_direction(0.001, 0.002), "中性")

    def test_realized_direction_from_series(self) -> None:
        nav = [
            {"date": "2026-03-01", "nav": 1.0},
            {"date": "2026-03-02", "nav": 1.01},
            {"date": "2026-03-03", "nav": 1.02},
            {"date": "2026-03-04", "nav": 1.03},
        ]
        realized = realized_direction_from_series(nav, "2026-03-01", horizon_days=2, neutral_band=0.001)
        assert realized is not None
        self.assertEqual(realized[0], "利好")
        self.assertAlmostEqual(realized[1], 0.02, places=6)

    def test_evaluate_prediction_rows(self) -> None:
        rows = [
            {"fund_code": "002963", "asof_date": "2026-03-01", "direction_3d": "利好", "direction_2w": "利好", "direction_3m": "利好"},
            {"fund_code": "002963", "asof_date": "2026-03-02", "direction_3d": "中性", "direction_2w": "利好", "direction_3m": "利好"},
        ]
        nav_by_fund = {
            "002963": [
                {"date": "2026-03-01", "nav": 1.00},
                {"date": "2026-03-02", "nav": 1.01},
                {"date": "2026-03-03", "nav": 1.03},
                {"date": "2026-03-04", "nav": 1.05},
                {"date": "2026-03-05", "nav": 1.06},
                {"date": "2026-03-06", "nav": 1.07},
                {"date": "2026-03-07", "nav": 1.08},
                {"date": "2026-03-08", "nav": 1.09},
                {"date": "2026-03-09", "nav": 1.10},
                {"date": "2026-03-10", "nav": 1.11},
                {"date": "2026-03-11", "nav": 1.12},
            ]
        }
        out = evaluate_prediction_rows(
            prediction_rows=rows,
            nav_by_fund=nav_by_fund,
            horizon_trading_days={"3d": 3, "2w": 5, "3m": 8},
            neutral_band_by_horizon={"3d": 0.002, "2w": 0.004, "3m": 0.008},
        )
        summary = out["summary"]
        self.assertIn("3d", summary)
        self.assertGreaterEqual(summary["3d"]["evaluable_rows"], 1)


if __name__ == "__main__":
    unittest.main()
