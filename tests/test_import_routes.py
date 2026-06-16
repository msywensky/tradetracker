from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as trade_app
from tracker.services.stats import compute_trade_stats


class ImportRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "import_test.db"

        self.original_db_path = trade_app.DB_PATH
        trade_app.DB_PATH = self.db_path
        trade_app.app.config["WTF_CSRF_ENABLED"] = False
        trade_app.init_db()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO accounts (short_name, full_name, fee_per_contract) VALUES (?, ?, ?)",
                ("IRA", "Rollover IRA", 0.65),
            )
            self.account_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        self.client = trade_app.app.test_client()

    def tearDown(self) -> None:
        trade_app.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_import_page_renders(self) -> None:
        res = self.client.get("/import")
        self.assertEqual(res.status_code, 200)

    def test_extract_missing_image_returns_400(self) -> None:
        res = self.client.post("/import/screenshot/extract", json={})
        self.assertEqual(res.status_code, 400)

    def test_extract_happy_path_groups_and_prices(self) -> None:
        fake_extraction = {
            "fills": [
                {"underlying": "QQQ", "option_type": "CALL", "expiration": "2026-06-17",
                 "strike": 734, "side": "SELL", "contracts": 10, "price_per_share": 4.82,
                 "timestamp": "2026-06-16 13:51:44", "account_label": "Rollover IRA *5675"},
                {"underlying": "QQQ", "option_type": "CALL", "expiration": "2026-06-17",
                 "strike": 734, "side": "BUY", "contracts": 10, "price_per_share": 4.25,
                 "timestamp": "2026-06-16 13:36:45", "account_label": "Rollover IRA *5675"},
            ]
        }
        with patch(
            "tracker.services.anthropic_client.extract_fills_from_image",
            return_value=fake_extraction,
        ):
            res = self.client.post(
                "/import/screenshot/extract",
                json={"image": "Zm9v", "media_type": "image/png"},
            )
        self.assertEqual(res.status_code, 200)
        trades = res.get_json()["trades"]
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["account_id"], self.account_id)
        self.assertEqual(trades[0]["status"], "CLOSED")
        self.assertEqual(trades[0]["entries"][0]["price"], 482.0)

    def test_commit_inserts_trades_and_entries(self) -> None:
        body = {
            "trades": [
                {
                    "symbol": "QQQ",
                    "option_type": "CALL",
                    "expiration": "2026-06-17",
                    "strike": 734,
                    "account_id": self.account_id,
                    "created_at": "2026-06-16 13:27:24",
                    "entries": [
                        {"side": "BUY", "contracts": 10, "price": 437.0},
                        {"side": "SELL", "contracts": 10, "price": 482.0},
                    ],
                }
            ]
        }
        res = self.client.post("/import/screenshot/commit", json=body)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["inserted"], 1)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            trade = conn.execute("SELECT * FROM trades").fetchone()
            self.assertEqual(trade["symbol"], "QQQ")
            self.assertEqual(trade["status"], "CLOSED")
            self.assertIsNotNone(trade["closed_at"])
            entries = conn.execute(
                "SELECT * FROM entries WHERE trade_id = ? ORDER BY id", (trade["id"],)
            ).fetchall()

        self.assertEqual(len(entries), 2)
        stats = compute_trade_stats(entries, fee_per_contract=0.65)
        # (482 - 437) * 10 = 450 before fees
        self.assertEqual(stats["pnl_before"], 450.0)

    def test_commit_empty_returns_400(self) -> None:
        res = self.client.post("/import/screenshot/commit", json={"trades": []})
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
