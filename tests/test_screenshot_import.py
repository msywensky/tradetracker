from __future__ import annotations

import unittest

from tracker.services.screenshot_import import build_preview, match_account


ACCOUNTS = [
    {"id": 1, "short_name": "INV", "full_name": "Individual Brokerage"},
    {"id": 2, "short_name": "IRA", "full_name": "Rollover IRA"},
]

# Modeled on trade-example.png.
SAMPLE_FILLS = [
    # QQQ call: 5 + 5 BUY, 10 SELL -> CLOSED
    {"underlying": "QQQ", "option_type": "CALL", "expiration": "2026-06-17", "strike": 734,
     "side": "SELL", "contracts": 10, "price_per_share": 4.82,
     "timestamp": "2026-06-16 13:51:44", "account_label": "Rollover IRA *5675"},
    {"underlying": "QQQ", "option_type": "CALL", "expiration": "2026-06-17", "strike": 734,
     "side": "BUY", "contracts": 5, "price_per_share": 4.25,
     "timestamp": "2026-06-16 13:36:45", "account_label": "Rollover IRA *5675"},
    {"underlying": "QQQ", "option_type": "CALL", "expiration": "2026-06-17", "strike": 734,
     "side": "BUY", "contracts": 5, "price_per_share": 4.49,
     "timestamp": "2026-06-16 13:27:24", "account_label": "Rollover IRA *5675"},
    # TSLA put: 10 BUY, 10 SELL -> CLOSED
    {"underlying": "TSLA", "option_type": "PUT", "expiration": "2026-06-17", "strike": 400,
     "side": "SELL", "contracts": 10, "price_per_share": 3.05,
     "timestamp": "2026-06-16 10:20:02", "account_label": "Rollover IRA *5675"},
    {"underlying": "TSLA", "option_type": "PUT", "expiration": "2026-06-17", "strike": 400,
     "side": "BUY", "contracts": 10, "price_per_share": 2.78,
     "timestamp": "2026-06-16 10:15:56", "account_label": "Rollover IRA *5675"},
]


class MatchAccountTests(unittest.TestCase):
    def test_matches_closest_full_name(self) -> None:
        self.assertEqual(match_account("Rollover IRA *5675", ACCOUNTS), 2)

    def test_no_match_returns_none(self) -> None:
        self.assertIsNone(match_account("Totally Unrelated Label zzz", ACCOUNTS))

    def test_empty_label_returns_none(self) -> None:
        self.assertIsNone(match_account("", ACCOUNTS))


class BuildPreviewTests(unittest.TestCase):
    def test_groups_fills_into_trades(self) -> None:
        trades = build_preview(SAMPLE_FILLS, ACCOUNTS)
        self.assertEqual(len(trades), 2)

    def test_qqq_trade_grouping_and_pricing(self) -> None:
        trades = build_preview(SAMPLE_FILLS, ACCOUNTS)
        qqq = next(t for t in trades if t["symbol"] == "QQQ")
        self.assertEqual(qqq["account_id"], 2)
        self.assertEqual(qqq["status"], "CLOSED")
        self.assertEqual(len(qqq["entries"]), 3)
        # Per-share 4.82 -> per-contract 482.0
        sell = next(e for e in qqq["entries"] if e["side"] == "SELL")
        self.assertEqual(sell["price"], 482.0)
        # Earliest fill timestamp becomes created_at.
        self.assertEqual(qqq["created_at"], "2026-06-16 13:27:24")

    def test_open_when_net_nonzero(self) -> None:
        fills = [
            {"underlying": "SPY", "option_type": "CALL", "expiration": "2026-06-20", "strike": 500,
             "side": "BUY", "contracts": 3, "price_per_share": 2.0,
             "timestamp": "2026-06-16 09:30:00", "account_label": "Individual Brokerage"},
        ]
        trades = build_preview(fills, ACCOUNTS)
        self.assertEqual(trades[0]["status"], "OPEN")

    def test_drops_invalid_fills(self) -> None:
        fills = [
            {"underlying": "", "option_type": "CALL", "side": "BUY", "contracts": 1,
             "price_per_share": 1.0, "account_label": "IRA"},
            {"underlying": "AAPL", "option_type": "CALL", "side": "BUY", "contracts": 0,
             "price_per_share": 1.0, "account_label": "IRA"},
            {"underlying": "AAPL", "option_type": "CALL", "side": "HOLD", "contracts": 1,
             "price_per_share": 1.0, "account_label": "IRA"},
        ]
        self.assertEqual(build_preview(fills, ACCOUNTS), [])


if __name__ == "__main__":
    unittest.main()
