import unittest

from src.pipeline.tasks import _decision_controls, _decision_readiness


class DirectEvidenceGateTests(unittest.TestCase):
    def test_decision_controls_loaded(self):
        cfg = _decision_controls()
        self.assertEqual(cfg["min_direct_main_by_fund_type"]["gold"], 1)
        self.assertEqual(cfg["min_direct_main_by_fund_type"]["bond"], 1)

    def test_below_direct_evidence_min_is_low_readiness(self):
        self.assertEqual(_decision_readiness("中", ["below_direct_evidence_min"]), "低")


if __name__ == "__main__":
    unittest.main()
