import unittest

from src.pipeline.tasks import _driver_coverage_summary


class GoldChainGateTests(unittest.TestCase):
    def test_gold_macro_chain_ready(self):
        checks = {"金价": "有覆盖", "美元": "有覆盖", "实际利率": "有覆盖", "避险": "证据不足", "央行购金": "证据不足", "ETF流向": "有覆盖"}
        summary = _driver_coverage_summary("gold", checks)
        self.assertTrue(summary["gold_macro_chain_ready"])
        self.assertTrue(summary["gold_etf_ready"])
        self.assertFalse(summary["gold_central_bank_ready"])


if __name__ == '__main__':
    unittest.main()
