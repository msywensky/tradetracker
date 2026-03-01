from __future__ import annotations

import unittest

from tracker.services.stats import compute_trade_stats


class ComputeTradeStatsTests(unittest.TestCase):
    def test_calculates_expected_fields(self) -> None:
        entries = [
            {"side": "BUY", "contracts": 2, "price": 100},
            {"side": "SELL", "contracts": 1, "price": 180},
            {"side": "SELL", "contracts": 1, "price": 140},
        ]

        stats = compute_trade_stats(entries, fee_per_contract=0.5)

        self.assertEqual(stats["buy_contracts"], 2)
        self.assertEqual(stats["sell_contracts"], 2)
        self.assertEqual(stats["total_contracts"], 4)
        self.assertEqual(stats["avg_buy"], 100)
        self.assertEqual(stats["avg_sell"], 160)
        self.assertEqual(stats["pnl_before"], 120)
        self.assertEqual(stats["fees"], 2.0)
        self.assertEqual(stats["pnl_after"], 118.0)
        # percent = pnl_before / max(buy_total, sell_total) * 100
        # = 120 / 320 * 100 = 37.5
        self.assertAlmostEqual(stats["percent"], 37.5)

    def test_handles_no_buy_safely(self) -> None:
        entries = [{"side": "SELL", "contracts": 1, "price": 100}]

        stats = compute_trade_stats(entries, fee_per_contract=0.65)

        self.assertEqual(stats["avg_buy"], 0)
        # percent = pnl_before / max(buy_total, sell_total) * 100
        # = 100 / 100 * 100 = 100.0 (full return on premium collected)
        self.assertAlmostEqual(stats["percent"], 100.0)


if __name__ == "__main__":
    unittest.main()
