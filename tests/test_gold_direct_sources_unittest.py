import unittest

from src.pipeline.tasks import _variable_evidence_meta


class GoldDirectSourceTests(unittest.TestCase):
    def test_gold_holdings_signal_is_direct(self):
        evidence_type, _ = _variable_evidence_meta("黄金ETF持仓变化趋势信号", "Gold Holdings Signal", "media")
        self.assertEqual(evidence_type, "direct")

    def test_central_bank_gold_signal_is_direct(self):
        evidence_type, _ = _variable_evidence_meta("央行购金趋势信号", "Central Bank Gold Signal", "media")
        self.assertEqual(evidence_type, "direct")


if __name__ == "__main__":
    unittest.main()
