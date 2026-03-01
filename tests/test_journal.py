
import sqlite3
import unittest
import tempfile
from pathlib import Path
from datetime import date
import app as trade_app


class JournalRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "journal_test.db"
        self.original_db_path = trade_app.DB_PATH
        trade_app.DB_PATH = self.db_path
        trade_app.app.config['WTF_CSRF_ENABLED'] = False
        trade_app.init_db()
        self.client = trade_app.app.test_client()

    def tearDown(self) -> None:
        trade_app.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    # ------------------------------------------------------------------ helpers

    def _insert_account(self, short_name: str = "TST") -> int:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO accounts (short_name, full_name, fee_per_contract) VALUES (?, ?, ?)",
                (short_name, f"{short_name} Account", 0.65),
            )
            return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    def _insert_trade(
        self,
        account_id: int,
        status: str = "OPEN",
        trade_code: str = "T-1",
        closed_at: str | None = None,
    ) -> int:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO trades
                    (trade_code, symbol, option_type, status, created_at, closed_at, notes, account_id, expiration, strike)
                VALUES (?, 'SPY', 'CALL', ?, '2026-01-01 10:00:00', ?, '', ?, NULL, NULL)
                """,
                (trade_code, status, closed_at, account_id),
            )
            return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    def _add_entry(self, text: str = "hello", **kwargs) -> int:
        """POST /journal/entry and return the HTTP status code."""
        payload = {"date": date.today().isoformat(), "text": text, **kwargs}
        resp = self.client.post("/journal/entry", json=payload)
        return resp.status_code

    # -------------------------------------------------------- /journal page

    def test_journal_page_renders(self):
        resp = self.client.get("/journal")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"journal", resp.data.lower())

    def test_journal_page_shows_existing_entries(self):
        self._add_entry(text="My first thought")
        resp = self.client.get("/journal")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"My first thought", resp.data)

    def test_journal_page_shows_closed_trade_today(self):
        account_id = self._insert_account()
        trade_id = self._insert_trade(
            account_id=account_id,
            status="CLOSED",
            trade_code="T-TODAY",
            closed_at=date.today().isoformat(),
        )
        resp = self.client.get("/journal")
        self.assertEqual(resp.status_code, 200)
        # The template renders the trade in a <select> as "(ID: {trade.id})"
        self.assertIn(f"(ID: {trade_id})".encode(), resp.data)

    # -------------------------------------------------------- POST /journal/entry

    def test_add_and_fetch_journal_entry(self):
        today = date.today().isoformat()
        resp = self.client.post("/journal/entry", json={
            "date": today,
            "text": "Test journal entry",
            "tags": "test,entry",
            "trade_id": None,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "success")

        resp = self.client.get("/journal/entries")
        self.assertEqual(resp.status_code, 200)
        entries = resp.get_json()
        self.assertTrue(any(e["text"] == "Test journal entry" for e in entries))

    def test_add_entry_with_title_and_tags(self):
        resp = self.client.post("/journal/entry", json={
            "date": date.today().isoformat(),
            "title": "Market recap",
            "text": "SPY made a big move today.",
            "tags": "spy,recap",
        })
        self.assertEqual(resp.status_code, 200)
        entries = self.client.get("/journal/entries").get_json()
        entry = next(e for e in entries if e["text"] == "SPY made a big move today.")
        self.assertEqual(entry["title"], "Market recap")
        self.assertEqual(entry["tags"], "spy,recap")

    def test_add_entry_linked_to_trade(self):
        account_id = self._insert_account()
        trade_id = self._insert_trade(account_id=account_id, trade_code="T-LINK")
        resp = self.client.post("/journal/entry", json={
            "date": date.today().isoformat(),
            "text": "Entered this trade for momentum.",
            "trade_id": trade_id,
        })
        self.assertEqual(resp.status_code, 200)

        entries = self.client.get("/journal/entries").get_json()
        linked = next(e for e in entries if e["text"] == "Entered this trade for momentum.")
        self.assertEqual(linked["trade_id"], trade_id)
        self.assertEqual(linked["trade_code"], "T-LINK")
        self.assertEqual(linked["symbol"], "SPY")

    def test_add_entry_defaults_date_when_omitted(self):
        resp = self.client.post("/journal/entry", json={"text": "No date given"})
        self.assertEqual(resp.status_code, 200)
        entries = self.client.get("/journal/entries").get_json()
        self.assertTrue(any(e["text"] == "No date given" for e in entries))

    def test_add_entry_rejects_invalid_date(self):
        resp = self.client.post("/journal/entry", json={
            "date": "not-a-date",
            "text": "Should fail",
        })
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["status"], "error")
        self.assertIn("date", body["message"].lower())

    def test_add_entry_rejects_empty_text(self):
        resp = self.client.post("/journal/entry", json={
            "date": date.today().isoformat(),
            "text": "   ",
        })
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["status"], "error")
        self.assertIn("text", body["message"].lower())

    def test_add_entry_rejects_missing_text(self):
        resp = self.client.post("/journal/entry", json={
            "date": date.today().isoformat(),
        })
        self.assertEqual(resp.status_code, 400)

    def test_add_entry_accepts_non_json_body(self):
        """get_json() returns None for non-JSON bodies; route should still respond."""
        resp = self.client.post(
            "/journal/entry",
            data="not json",
            content_type="text/plain",
        )
        # Missing text → 400, but the route must not crash with 500
        self.assertNotEqual(resp.status_code, 500)

    # -------------------------------------------------------- GET /journal/entries

    def test_entries_empty_initially(self):
        resp = self.client.get("/journal/entries")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), [])

    def test_entries_returns_multiple(self):
        self._add_entry(text="Alpha")
        self._add_entry(text="Beta")
        entries = self.client.get("/journal/entries").get_json()
        texts = [e["text"] for e in entries]
        self.assertIn("Alpha", texts)
        self.assertIn("Beta", texts)

    # -------------------------------------------------------- GET /journal/entries/<date>

    def test_entries_for_date_filters_correctly(self):
        self.client.post("/journal/entry", json={"date": "2026-01-10", "text": "January entry"})
        self.client.post("/journal/entry", json={"date": "2026-02-15", "text": "February entry"})

        jan = self.client.get("/journal/entries/2026-01-10").get_json()
        self.assertEqual(len(jan), 1)
        self.assertEqual(jan[0]["text"], "January entry")

        feb = self.client.get("/journal/entries/2026-02-15").get_json()
        self.assertEqual(len(feb), 1)
        self.assertEqual(feb[0]["text"], "February entry")

    def test_entries_for_date_returns_empty_list_when_none(self):
        resp = self.client.get("/journal/entries/2025-01-01")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), [])

    def test_entries_for_date_includes_trade_context(self):
        account_id = self._insert_account()
        trade_id = self._insert_trade(account_id=account_id, trade_code="T-DATE")
        self.client.post("/journal/entry", json={
            "date": "2026-03-01",
            "text": "Linked to a trade",
            "trade_id": trade_id,
        })
        entries = self.client.get("/journal/entries/2026-03-01").get_json()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["trade_code"], "T-DATE")
        self.assertEqual(entries[0]["symbol"], "SPY")

    # -------------------------------------------------------- GET /journal/closed_trades_today

    def test_closed_trades_today_empty(self):
        resp = self.client.get("/journal/closed_trades_today")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.get_json(), list)

    def test_closed_trades_today_returns_closed_trade(self):
        account_id = self._insert_account()
        self._insert_trade(
            account_id=account_id,
            status="CLOSED",
            trade_code="T-CLOSED-TODAY",
            closed_at=date.today().isoformat(),
        )
        trades = self.client.get("/journal/closed_trades_today").get_json()
        codes = [t["trade_code"] for t in trades]
        self.assertIn("T-CLOSED-TODAY", codes)

    def test_closed_trades_today_excludes_open_trades(self):
        account_id = self._insert_account()
        self._insert_trade(account_id=account_id, status="OPEN", trade_code="T-OPEN-1")
        trades = self.client.get("/journal/closed_trades_today").get_json()
        codes = [t["trade_code"] for t in trades]
        self.assertNotIn("T-OPEN-1", codes)

    def test_closed_trades_today_excludes_old_closed_trades(self):
        account_id = self._insert_account()
        self._insert_trade(
            account_id=account_id,
            status="CLOSED",
            trade_code="T-OLD",
            closed_at="2025-01-01",
        )
        trades = self.client.get("/journal/closed_trades_today").get_json()
        codes = [t["trade_code"] for t in trades]
        self.assertNotIn("T-OLD", codes)


if __name__ == "__main__":
    unittest.main()
