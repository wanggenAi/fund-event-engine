import unittest

from src.pipeline.tasks import _variable_evidence_meta


class BondDirectSourceTests(unittest.TestCase):
    def test_china_bond_credit_signal_is_direct(self):
        evidence_type, _ = _variable_evidence_meta("中国信用债风险事件趋势信号", "China Bond Credit Signal", "media")
        self.assertEqual(evidence_type, "direct")

    def test_bond_financing_signal_is_direct(self):
        evidence_type, _ = _variable_evidence_meta("信用债发行与净融资趋势信号", "Bond Financing Signal", "media")
        self.assertEqual(evidence_type, "direct")


if __name__ == "__main__":
    unittest.main()
