import unittest

from src.pipeline.tasks import _variable_evidence_meta


class RareEarthDirectSourceTests(unittest.TestCase):
    def test_rare_earth_policy_signal_is_direct(self):
        evidence_type, _ = _variable_evidence_meta("稀土政策与供给约束趋势信号", "Rare Earth Policy Direct Signal", "media")
        self.assertEqual(evidence_type, "direct")

    def test_rare_earth_price_signal_is_direct(self):
        evidence_type, _ = _variable_evidence_meta("稀土价格趋势信号", "Rare Earth Price Direct Signal", "media")
        self.assertEqual(evidence_type, "direct")


if __name__ == "__main__":
    unittest.main()
