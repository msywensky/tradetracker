from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import import_trades_csv as importer


class ImportTradesCsvTests(unittest.TestCase):
    def test_convert_csv_price_to_x100(self) -> None:
        self.assertEqual(importer.convert_csv_price_to_x100(125.0, "per-contract"), 125)
        self.assertEqual(importer.convert_csv_price_to_x100(1.25, "per-share"), 125)
        self.assertEqual(importer.convert_csv_price_to_x100(214.60, "per-contract"), 214.6)

    def test_load_trade_rows_finds_header_after_preamble(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "trades.csv"
            csv_path.write_text(
                "Report Name,Trade Export\n"
                "Generated,2026-02-15\n"
                "Date,Opts Traded,Avg Buy,Avg Sell,Account,Notes\n"
                "02/13 10:00 AM,2,125.00,155.00,INV,SPY scalp\n",
                encoding="utf-8",
            )

            rows = importer.load_trade_rows(csv_path)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["date"], "02/13 10:00 AM")
            self.assertEqual(rows[0]["avg buy"], "125.00")

    def test_load_trade_rows_supports_cp1252_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "trades_cp1252.csv"
            csv_text = (
                "Date,Opts Traded,Avg Buy,Avg Sell,Account,Notes\n"
                "02/13 10:00 AM,2,125.00,155.00,IRA,Should’ve sold runner\n"
            )
            csv_path.write_bytes(csv_text.encode("cp1252"))

            rows = importer.load_trade_rows(csv_path)

            self.assertEqual(len(rows), 1)
            self.assertIn("Should", rows[0]["notes"])

    def test_import_csv_inserts_weekday_and_skips_weekend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "import_test.db"
            csv_path = Path(temp_dir) / "trades.csv"
            csv_path.write_text(
                "Date,Opts Traded,Avg Buy,Avg Sell,Account,Notes\n"
                "02/13 10:00 AM,2,125.00,155.00,INV,SPY weekday\n"
                "02/14 09:45 AM,1,210.00,180.00,IRA,TSLA weekend\n",
                encoding="utf-8",
            )

            importer.import_csv(
                db_path=db_path,
                csv_path=csv_path,
                default_year=2026,
                price_unit="per-contract",
                contracts_unit="round-trip-total",
            )

            conn = sqlite3.connect(db_path)
            try:
                trades_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
                entries = conn.execute(
                    "SELECT side, contracts, price FROM entries ORDER BY id"
                ).fetchall()
            finally:
                conn.close()

            self.assertEqual(trades_count, 1)
            self.assertEqual(entries, [("BUY", 1, 125), ("SELL", 1, 155)])

    def test_convert_opts_traded_to_entry_contracts(self) -> None:
        self.assertEqual(
            importer.convert_opts_traded_to_entry_contracts(10, "round-trip-total"),
            (5, 5),
        )
        self.assertIsNone(importer.convert_opts_traded_to_entry_contracts(1, "round-trip-total"))
        self.assertIsNone(importer.convert_opts_traded_to_entry_contracts(3, "round-trip-total"))
        self.assertEqual(
            importer.convert_opts_traded_to_entry_contracts(3, "per-side"),
            (3, 3),
        )

    def test_prompt_clear_tables_non_interactive_defaults_false(self) -> None:
        class _FakeStdin:
            @staticmethod
            def isatty() -> bool:
                return False

        original_stdin = importer.sys.stdin
        importer.sys.stdin = _FakeStdin()
        try:
            self.assertFalse(importer.prompt_clear_tables())
        finally:
            importer.sys.stdin = original_stdin

    def test_clear_trades_and_entries_also_clears_daily_balances(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "clear_test.db"
            conn = sqlite3.connect(db_path)
            try:
                importer.ensure_schema(conn)
                conn.execute(
                    "INSERT INTO trades (trade_code, symbol, status, created_at, closed_at, notes, account_id) "
                    "VALUES ('T-1', 'SPY', 'CLOSED', '2026-02-13 10:00:00', '2026-02-13', '', NULL)"
                )
                trade_id = conn.execute("SELECT id FROM trades WHERE trade_code='T-1'").fetchone()[0]
                conn.execute(
                    "INSERT INTO entries (trade_id, side, contracts, price, created_at) "
                    "VALUES (?, 'BUY', 1, 100, '2026-02-13 10:00:00')",
                    (trade_id,),
                )
                conn.execute(
                    "INSERT INTO daily_balances (date, account_id, balance) VALUES ('2026-02-13', 1, 10000)"
                )
                conn.commit()
            finally:
                conn.close()

            importer.clear_trades_and_entries(db_path)

            conn = sqlite3.connect(db_path)
            try:
                trades_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
                entries_count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
                balances_count = conn.execute("SELECT COUNT(*) FROM daily_balances").fetchone()[0]
            finally:
                conn.close()

            self.assertEqual(trades_count, 0)
            self.assertEqual(entries_count, 0)
            self.assertEqual(balances_count, 0)

    def test_detect_csv_kind_for_balance_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "balances.csv"
            csv_path.write_text(
                "date,account,balance\n"
                "01-02,brokerage,$50,000.00\n",
                encoding="utf-8",
            )

            self.assertEqual(importer.detect_csv_kind(csv_path), "balance")

    def test_import_balance_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "balances_test.db"
            csv_path = Path(temp_dir) / "balances.csv"
            csv_path.write_text(
                "date,account,balance\n"
                "01-02,brokerage,\"$50,093.50\"\n"
                "01-03,IRA,\"$7,204.60\"\n",
                encoding="utf-8",
            )

            importer.import_balance_csv(db_path, csv_path, default_year=2026)

            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute(
                    """
                    SELECT d.date, a.short_name, d.balance
                    FROM daily_balances d
                    JOIN accounts a ON a.id = d.account_id
                    ORDER BY d.date, a.short_name
                    """
                ).fetchall()
            finally:
                conn.close()

            self.assertEqual(rows, [("2026-01-02", "BROKERAGE", 50093.5), ("2026-01-03", "IRA", 7204.6)])


if __name__ == "__main__":
    unittest.main()