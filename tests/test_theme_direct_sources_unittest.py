import unittest

from src.pipeline.tasks import _variable_evidence_meta


class ThemeDirectSourceTests(unittest.TestCase):
    def test_power_grid_tender_signal_is_direct(self):
        evidence_type, _ = _variable_evidence_meta("电网招投标与订单趋势信号", "Power Grid Tender Signal", "media")
        self.assertEqual(evidence_type, "direct")

    def test_satellite_launch_signal_is_direct(self):
        evidence_type, _ = _variable_evidence_meta("商用卫星发射与组网趋势信号", "Satellite Launch Signal", "media")
        self.assertEqual(evidence_type, "direct")


if __name__ == "__main__":
    unittest.main()
