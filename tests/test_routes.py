from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

import app as trade_app


class RouteIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "routes_test.db"

        self.original_db_path = trade_app.DB_PATH
        trade_app.DB_PATH = self.db_path
        trade_app.app.config['WTF_CSRF_ENABLED'] = False
        trade_app.init_db()

        self.client = trade_app.app.test_client()

    def tearDown(self) -> None:
        trade_app.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def _insert_account(self, short_name: str = "INV", fee: float = 0.65) -> int:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO accounts (short_name, full_name, fee_per_contract) VALUES (?, ?, ?)",
                (short_name, f"{short_name} Account", fee),
            )
            return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    def _insert_trade(
        self,
        account_id: int | None,
        status: str = "OPEN",
        trade_code: str = "T-1",
        created_at: str = "2026-02-10 10:00:00",
        closed_at: str | None = None,
    ) -> int:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO trades (trade_code, symbol, option_type, status, created_at, closed_at, notes, account_id, expiration, strike)
                VALUES (?, 'SPY', 'CALL', ?, ?, ?, '', ?, NULL, NULL)
                """,
                (trade_code, status, created_at, closed_at, account_id),
            )
            return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    def _insert_entry(
        self,
        trade_id: int,
        side: str,
        contracts: int,
        price: int,
        created_at: str = "2026-02-10 10:00:00",
    ) -> int:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO entries (trade_id, side, contracts, price, created_at) VALUES (?, ?, ?, ?, ?)",
                (trade_id, side, contracts, price, created_at),
            )
            return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    def test_get_routes_render_successfully(self) -> None:
        account_id = self._insert_account()
        closed_today = self._insert_trade(
            account_id=account_id,
            status="CLOSED",
            trade_code="T-CLOSED",
            closed_at=date.today().isoformat(),
        )
        self._insert_entry(closed_today, "BUY", 1, 100)
        self._insert_entry(closed_today, "SELL", 1, 120)

        responses = [
            self.client.get("/"),
            self.client.get("/accounts"),
            self.client.get(f"/month/{date.today().year}/{date.today().month}"),
            self.client.get(f"/ytd/{date.today().year}"),
            self.client.get("/analysis"),
        ]

        for response in responses:
            self.assertEqual(response.status_code, 200)

    def test_account_create_update_set_default_and_delete(self) -> None:
        create_response = self.client.post(
            "/account/create",
            data={"short_name": "ira", "full_name": "IRA Account", "fee_per_contract": "0.50"},
        )
        self.assertEqual(create_response.status_code, 302)

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id, short_name, full_name, fee_per_contract FROM accounts WHERE short_name='IRA'"
            ).fetchone()
            self.assertIsNotNone(row)
            account_id = int(row[0])

        update_response = self.client.post(
            f"/account/{account_id}/update",
            data={"short_name": "IRA2", "full_name": "IRA Updated", "fee_per_contract": "0.75"},
        )
        self.assertEqual(update_response.status_code, 302)

        default_response = self.client.post(f"/account/{account_id}/set-default")
        self.assertEqual(default_response.status_code, 302)

        with sqlite3.connect(self.db_path) as conn:
            setting = conn.execute(
                "SELECT value FROM app_settings WHERE key='default_account_id'"
            ).fetchone()
            self.assertEqual(setting[0], str(account_id))

        delete_response = self.client.post(f"/account/{account_id}/delete")
        self.assertEqual(delete_response.status_code, 302)

        with sqlite3.connect(self.db_path) as conn:
            still_exists = conn.execute("SELECT id FROM accounts WHERE id = ?", (account_id,)).fetchone()
            self.assertIsNone(still_exists)

    def test_account_delete_is_blocked_when_trades_exist(self) -> None:
        account_id = self._insert_account("BLK", 0.65)
        self._insert_trade(account_id=account_id, status="OPEN", trade_code="BLK-1")

        response = self.client.post(f"/account/{account_id}/delete")
        self.assertEqual(response.status_code, 302)
        self.assertIn("account_error=Account+has+associated+trades", response.location)

    def test_trade_create_and_detail(self) -> None:
        account_id = self._insert_account("TRD", 0.65)

        response = self.client.post(
            "/trade/create",
            data={
                "trade_code": "",
                "symbol": "spy",
                "option_type": "PUT",
                "account_id": str(account_id),
                "expiration": "2026-03-20",
                "strike": "520",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/trade/", response.location)

        trade_id = int(response.location.rsplit("/", 1)[1])
        detail = self.client.get(f"/trade/{trade_id}")
        self.assertEqual(detail.status_code, 200)

        with sqlite3.connect(self.db_path) as conn:
            trade_row = conn.execute(
                "SELECT symbol, option_type, expiration, strike FROM trades WHERE id = ?",
                (trade_id,),
            ).fetchone()
            self.assertEqual(trade_row, ("SPY", "PUT", "2026-03-20", 520.0))

    def test_entry_add_update_delete_routes(self) -> None:
        account_id = self._insert_account("ENT", 0.65)
        trade_id = self._insert_trade(account_id=account_id, trade_code="ENT-1")

        add_response = self.client.post(
            f"/trade/{trade_id}/entry",
            data={"side": "BUY", "contracts": "2", "price": "100"},
        )
        self.assertEqual(add_response.status_code, 302)

        with sqlite3.connect(self.db_path) as conn:
            entry = conn.execute(
                "SELECT id, side, contracts, price FROM entries WHERE trade_id=?",
                (trade_id,),
            ).fetchone()
            self.assertIsNotNone(entry)
            entry_id = int(entry[0])

        update_response = self.client.post(
            f"/entry/{entry_id}/update",
            data={"trade_id": str(trade_id), "side": "SELL", "contracts": "1", "price": "150"},
        )
        self.assertEqual(update_response.status_code, 302)

        with sqlite3.connect(self.db_path) as conn:
            updated = conn.execute("SELECT side, contracts, price FROM entries WHERE id=?", (entry_id,)).fetchone()
            self.assertEqual(updated, ("SELL", 1, 150))

        delete_response = self.client.post(f"/entry/{entry_id}/delete")
        self.assertEqual(delete_response.status_code, 302)

        with sqlite3.connect(self.db_path) as conn:
            deleted = conn.execute("SELECT id FROM entries WHERE id=?", (entry_id,)).fetchone()
            self.assertIsNone(deleted)

    def test_close_trade_requires_flat_position_then_closes(self) -> None:
        account_id = self._insert_account("CLS", 0.0)
        trade_id = self._insert_trade(account_id=account_id, trade_code="CLS-1")

        self._insert_entry(trade_id, "BUY", 2, 100)
        self._insert_entry(trade_id, "SELL", 1, 120)

        blocked_response = self.client.post(f"/trade/{trade_id}/close", data={"notes": "blocked"})
        self.assertEqual(blocked_response.status_code, 302)
        self.assertTrue(blocked_response.location.endswith(f"/trade/{trade_id}"))

        self._insert_entry(trade_id, "SELL", 1, 125)
        close_response = self.client.post(f"/trade/{trade_id}/close", data={"notes": "done"})
        self.assertEqual(close_response.status_code, 302)
        self.assertIn(f"/month/{date.today().year}/{date.today().month}", close_response.location)

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT status, closed_at, notes FROM trades WHERE id=?", (trade_id,)).fetchone()
            self.assertEqual(row[0], "CLOSED")
            self.assertEqual(row[1], date.today().isoformat())
            self.assertEqual(row[2], "done")

    def test_save_open_duplicate_and_delete_trade_routes(self) -> None:
        account_id = self._insert_account("DUP", 0.65)
        trade_id = self._insert_trade(account_id=account_id, trade_code="DUP-1")

        save_open_response = self.client.post(f"/trade/{trade_id}/save-open", data={"notes": "keep open"})
        self.assertEqual(save_open_response.status_code, 302)

        with sqlite3.connect(self.db_path) as conn:
            notes = conn.execute("SELECT notes FROM trades WHERE id=?", (trade_id,)).fetchone()[0]
            self.assertEqual(notes, "keep open")

        duplicate_response = self.client.post(f"/trade/{trade_id}/duplicate")
        self.assertEqual(duplicate_response.status_code, 302)
        new_trade_id = int(duplicate_response.location.rsplit("/", 1)[1])

        with sqlite3.connect(self.db_path) as conn:
            duplicated = conn.execute("SELECT status, account_id FROM trades WHERE id=?", (new_trade_id,)).fetchone()
            self.assertEqual(duplicated, ("OPEN", account_id))

        delete_response = self.client.post(
            f"/trade/{new_trade_id}/delete",
            data={"return_view": "month", "return_year": str(date.today().year), "return_month": str(date.today().month), "return_account": str(account_id)},
        )
        self.assertEqual(delete_response.status_code, 302)
        self.assertIn(f"/month/{date.today().year}/{date.today().month}?account={account_id}", delete_response.location)

        with sqlite3.connect(self.db_path) as conn:
            deleted = conn.execute("SELECT id FROM trades WHERE id=?", (new_trade_id,)).fetchone()
            self.assertIsNone(deleted)

    def test_balance_routes_create_and_update(self) -> None:
        account_id = self._insert_account("BAL", 0.65)

        create_response = self.client.post(
            "/balance/create",
            data={"date": "2026-02-15", "account_id": str(account_id), "balance": "15000.50"},
        )
        self.assertEqual(create_response.status_code, 302)
        self.assertTrue(create_response.location.endswith("/#balances"))

        update_response = self.client.post(
            "/month/balance",
            data={
                "date": "2026-02-15",
                "year": "2026",
                "month": "2",
                "account_id": str(account_id),
                "balance": "15111.00",
            },
        )
        self.assertEqual(update_response.status_code, 302)
        self.assertIn(f"/month/2026/2?account={account_id}", update_response.location)

        with sqlite3.connect(self.db_path) as conn:
            balance = conn.execute(
                "SELECT balance FROM daily_balances WHERE date='2026-02-15' AND account_id=?",
                (account_id,),
            ).fetchone()[0]
            self.assertAlmostEqual(balance, 15111.0)

    def test_analysis_preferences_saved_to_db(self) -> None:
        payload = {
            "order": ["chart4", "chart1", "chart2"],
            "visible": {
                "chart1": True,
                "chart2": False,
                "chart4": True,
            },
        }

        response = self.client.post("/analysis/preferences", json=payload)
        self.assertEqual(response.status_code, 200)

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key='analysis_chart_preferences'"
            ).fetchone()

        self.assertIsNotNone(row)
        saved = json.loads(row[0])
        self.assertEqual(saved["order"][:3], ["chart4", "chart1", "chart2"])
        self.assertFalse(saved["visible"]["chart2"])


if __name__ == "__main__":
    unittest.main()
