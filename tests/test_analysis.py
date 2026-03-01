from __future__ import annotations

import json
import re
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
import time

import app as trade_app


class AnalysisRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "analysis_test.db"

        self.original_db_path = trade_app.DB_PATH
        trade_app.DB_PATH = self.db_path
        trade_app.app.config['WTF_CSRF_ENABLED'] = False
        trade_app.init_db()

        self.client = trade_app.app.test_client()

    def tearDown(self) -> None:
        trade_app.DB_PATH = self.original_db_path
        time.sleep(0.1)  # Small delay for Windows file lock
        self.temp_dir.cleanup()

    def _insert_account(self, short_name: str, fee_per_contract: float) -> int:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO accounts (short_name, full_name, fee_per_contract) VALUES (?, ?, ?)",
                (short_name, f"{short_name} Account", fee_per_contract),
            )
            return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    def _insert_closed_trade(
        self,
        trade_code: str,
        account_id: int,
        created_at: str,
        closed_at: str,
        buy_price: int,
        sell_price: int,
        contracts: int = 1,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO trades (trade_code, symbol, option_type, status, created_at, closed_at, account_id)
                VALUES (?, 'SPY', 'CALL', 'CLOSED', ?, ?, ?)
                """,
                (trade_code, created_at, closed_at, account_id),
            )
            trade_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.execute(
                """
                INSERT INTO entries (trade_id, side, contracts, price, created_at)
                VALUES (?, 'BUY', ?, ?, ?)
                """,
                (trade_id, contracts, buy_price, created_at),
            )
            conn.execute(
                """
                INSERT INTO entries (trade_id, side, contracts, price, created_at)
                VALUES (?, 'SELL', ?, ?, ?)
                """,
                (trade_id, contracts, sell_price, created_at),
            )

    def _insert_balance(self, balance_date: str, account_id: int, balance: float) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO daily_balances (date, account_id, balance)
                VALUES (?, ?, ?)
                """,
                (balance_date, account_id, balance),
            )

    def _extract_chart(self, html: str, chart_number: int) -> dict:
        match = re.search(
            rf"var chart{chart_number}_data = (\{{.*?\}});",
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            f"chart{chart_number}_data JSON was not found in analysis response",
        )
        return json.loads(match.group(1))

    def _monthly_values(self, chart3: dict) -> dict[str, float]:
        labels = chart3["data"][0]["x"]
        values = chart3["data"][0]["y"]
        return {label: float(value) for label, value in zip(labels, values)}

    def _seed_analysis_dataset(self) -> tuple[int, str, str]:
        today = date.today()
        previous_month_year = today.year if today.month > 1 else today.year - 1
        previous_month = today.month - 1 if today.month > 1 else 12

        current_day_1 = f"{today.year}-{today.month:02d}-03"
        current_day_2 = f"{today.year}-{today.month:02d}-10"
        previous_day = f"{previous_month_year}-{previous_month:02d}-12"

        account_id = self._insert_account("ANA", 0.0)

        self._insert_closed_trade(
            trade_code="ANA-WIN-1",
            account_id=account_id,
            created_at=f"{current_day_1} 10:00:00",
            closed_at=current_day_1,
            buy_price=100,
            sell_price=150,
        )
        self._insert_closed_trade(
            trade_code="ANA-LOSE-1",
            account_id=account_id,
            created_at=f"{current_day_1} 11:00:00",
            closed_at=current_day_1,
            buy_price=100,
            sell_price=80,
        )
        self._insert_closed_trade(
            trade_code="ANA-WIN-2",
            account_id=account_id,
            created_at=f"{current_day_2} 10:00:00",
            closed_at=current_day_2,
            buy_price=100,
            sell_price=140,
        )
        self._insert_closed_trade(
            trade_code="ANA-LOSE-2",
            account_id=account_id,
            created_at=f"{current_day_2} 11:00:00",
            closed_at=current_day_2,
            buy_price=100,
            sell_price=90,
        )
        self._insert_closed_trade(
            trade_code="ANA-PREV-1",
            account_id=account_id,
            created_at=f"{previous_day} 09:45:00",
            closed_at=previous_day,
            buy_price=100,
            sell_price=130,
        )
        self._insert_closed_trade(
            trade_code="ANA-PREV-2",
            account_id=account_id,
            created_at=f"{previous_day} 10:30:00",
            closed_at=previous_day,
            buy_price=100,
            sell_price=85,
        )

        self._insert_balance(previous_day, account_id, 10000)
        self._insert_balance(current_day_1, account_id, 10100)
        self._insert_balance(current_day_2, account_id, 10080)

        return account_id, current_day_1, current_day_2

    def test_analysis_month_view_includes_expected_chart_payloads(self) -> None:
        account_id, current_day_1, current_day_2 = self._seed_analysis_dataset()

        response = self.client.get(f"/analysis?account={account_id}&view=month")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        chart1 = self._extract_chart(html, 1)
        chart2 = self._extract_chart(html, 2)
        chart3 = self._extract_chart(html, 3)
        chart4 = self._extract_chart(html, 4)
        chart5 = self._extract_chart(html, 5)
        chart6 = self._extract_chart(html, 6)
        chart7 = self._extract_chart(html, 7)
        chart8 = self._extract_chart(html, 8)

        self.assertEqual(chart1["data"][0]["x"], [current_day_1, current_day_2])
        self.assertEqual([float(v) for v in chart1["data"][0]["y"]], [30.0, 30.0])

        self.assertEqual(chart2["data"][0]["x"], [current_day_1, current_day_2])
        self.assertEqual([float(v) for v in chart2["data"][0]["y"]], [50.0, 50.0])

        monthly = self._monthly_values(chart3)
        month_label = date.today().strftime("%b %Y")
        self.assertAlmostEqual(monthly[month_label], 60.0)

        self.assertEqual(chart4["data"][0]["x"], [
            f"{date.today().year if date.today().month > 1 else date.today().year - 1}-{(date.today().month - 1 if date.today().month > 1 else 12):02d}-12",
            current_day_1,
            current_day_2,
        ])
        self.assertEqual([float(v) for v in chart4["data"][0]["y"]], [10000.0, 10100.0, 10080.0])

        self.assertEqual([float(v) for v in chart5["data"][0]["x"]], [50.0, 50.0])
        self.assertEqual([float(v) for v in chart5["data"][0]["y"]], [30.0, 30.0])
        self.assertEqual([float(v) for v in chart6["data"][0]["x"]], [2.0, 2.0])
        self.assertEqual([float(v) for v in chart6["data"][0]["y"]], [30.0, 30.0])
        self.assertEqual([float(v) for v in chart7["data"][0]["x"]], [2.5, 4.0])
        self.assertEqual([float(v) for v in chart7["data"][0]["y"]], [30.0, 30.0])
        self.assertEqual(chart8["data"][0]["x"], ["Mon", "Tue", "Wed", "Thu", "Fri"])
        day_values = [float(v) for v in chart8["data"][0]["y"]]
        self.assertAlmostEqual(sum(day_values), 60.0)
        non_zero = sorted([round(v, 2) for v in day_values if abs(v) > 1e-9])
        self.assertEqual(non_zero, [60.0])
        self.assertIn("Correlation:", html)

    def test_analysis_ytd_view_daily_and_win_loss_include_prior_month(self) -> None:
        account_id, current_day_1, current_day_2 = self._seed_analysis_dataset()
        today = date.today()
        previous_month_year = today.year if today.month > 1 else today.year - 1
        previous_month = today.month - 1 if today.month > 1 else 12
        previous_day = f"{previous_month_year}-{previous_month:02d}-12"

        response = self.client.get(f"/analysis?account={account_id}&view=ytd")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        chart1 = self._extract_chart(html, 1)
        chart2 = self._extract_chart(html, 2)
        chart5 = self._extract_chart(html, 5)
        chart6 = self._extract_chart(html, 6)
        chart7 = self._extract_chart(html, 7)
        chart8 = self._extract_chart(html, 8)

        self.assertEqual(chart1["data"][0]["x"], [previous_day, current_day_1, current_day_2])
        self.assertEqual([float(v) for v in chart1["data"][0]["y"]], [15.0, 30.0, 30.0])

        previous_week = (date.fromisoformat(previous_day) - timedelta(days=date.fromisoformat(previous_day).weekday())).isoformat()
        current_week_1 = (date.fromisoformat(current_day_1) - timedelta(days=date.fromisoformat(current_day_1).weekday())).isoformat()
        current_week_2 = (date.fromisoformat(current_day_2) - timedelta(days=date.fromisoformat(current_day_2).weekday())).isoformat()

        self.assertEqual(chart2["data"][0]["x"], [previous_week, current_week_1, current_week_2])
        self.assertEqual([float(v) for v in chart2["data"][0]["y"]], [50.0, 50.0, 50.0])

        self.assertEqual([float(v) for v in chart5["data"][0]["x"]], [50.0, 50.0, 50.0])
        self.assertEqual([float(v) for v in chart5["data"][0]["y"]], [15.0, 30.0, 30.0])
        self.assertEqual([float(v) for v in chart6["data"][0]["x"]], [2.0, 2.0, 2.0])
        self.assertEqual([float(v) for v in chart6["data"][0]["y"]], [15.0, 30.0, 30.0])
        self.assertEqual([float(v) for v in chart7["data"][0]["x"]], [2.0, 2.5, 4.0])
        self.assertEqual([float(v) for v in chart7["data"][0]["y"]], [15.0, 30.0, 30.0])
        self.assertEqual(chart8["data"][0]["x"], ["Mon", "Tue", "Wed", "Thu", "Fri"])
        ytd_day_values = [float(v) for v in chart8["data"][0]["y"]]
        self.assertAlmostEqual(sum(ytd_day_values), 75.0)
        ytd_non_zero = sorted([round(v, 2) for v in ytd_day_values if abs(v) > 1e-9])
        self.assertEqual(ytd_non_zero, [15.0, 60.0])
        self.assertIn("Correlation:", html)

    def test_monthly_pnl_comparison_respects_zero_account_fee(self) -> None:
        account_id = self._insert_account("ZERO", 0.0)

        self._insert_closed_trade(
            trade_code="ZERO-1",
            account_id=account_id,
            created_at="2026-01-03 10:00:00",
            closed_at="2026-01-03",
            buy_price=100,
            sell_price=200,
        )
        self._insert_closed_trade(
            trade_code="ZERO-2",
            account_id=account_id,
            created_at="2026-01-10 11:00:00",
            closed_at="2026-01-10",
            buy_price=100,
            sell_price=50,
        )
        self._insert_closed_trade(
            trade_code="ZERO-3",
            account_id=account_id,
            created_at="2026-02-04 09:30:00",
            closed_at="2026-02-04",
            buy_price=100,
            sell_price=130,
        )

        response = self.client.get(f"/analysis?account={account_id}&view=ytd")
        self.assertEqual(response.status_code, 200)

        chart3 = self._extract_chart(response.get_data(as_text=True), 3)
        monthly = self._monthly_values(chart3)

        self.assertAlmostEqual(monthly["Jan 2026"], 50.0)
        self.assertAlmostEqual(monthly["Feb 2026"], 30.0)

    def test_analysis_ytd_chart3_monthly_pnl_values(self) -> None:
        """chart3 in YTD view shows correct per-month P&L bars."""
        account_id, current_day_1, current_day_2 = self._seed_analysis_dataset()
        today = date.today()

        response = self.client.get(f"/analysis?account={account_id}&view=ytd")
        self.assertEqual(response.status_code, 200)
        chart3 = self._extract_chart(response.get_data(as_text=True), 3)
        monthly = self._monthly_values(chart3)

        month_label = today.strftime("%b %Y")
        # current month: 4 trades, net P&L = (150-100)+(80-100)+(140-100)+(90-100) = 50+(-20)+40+(-10) = 60
        self.assertAlmostEqual(monthly[month_label], 60.0)

        previous_month_year = today.year if today.month > 1 else today.year - 1
        previous_month = today.month - 1 if today.month > 1 else 12
        prev_label = date(previous_month_year, previous_month, 1).strftime("%b %Y")
        # previous month: 2 trades, net P&L = (130-100)+(85-100) = 30+(-15) = 15
        self.assertAlmostEqual(monthly[prev_label], 15.0)

    def test_analysis_ytd_chart4_balance_trend(self) -> None:
        """chart4 in YTD view shows account balance history across all inserted dates."""
        account_id, current_day_1, current_day_2 = self._seed_analysis_dataset()
        today = date.today()
        previous_month_year = today.year if today.month > 1 else today.year - 1
        previous_month = today.month - 1 if today.month > 1 else 12
        previous_day = f"{previous_month_year}-{previous_month:02d}-12"

        response = self.client.get(f"/analysis?account={account_id}&view=ytd")
        self.assertEqual(response.status_code, 200)
        chart4 = self._extract_chart(response.get_data(as_text=True), 4)

        dates = chart4["data"][0]["x"]
        values = [float(v) for v in chart4["data"][0]["y"]]

        self.assertEqual(dates, [previous_day, current_day_1, current_day_2])
        self.assertEqual(values, [10000.0, 10100.0, 10080.0])

    def test_analysis_chart4_null_when_no_balance_data(self) -> None:
        """chart4 must not appear in the response when no daily_balances exist."""
        account_id = self._insert_account("NOBAL", 0.0)
        self._insert_closed_trade(
            trade_code="NOBAL-1",
            account_id=account_id,
            created_at="2026-01-03 10:00:00",
            closed_at="2026-01-03",
            buy_price=100,
            sell_price=150,
        )

        response = self.client.get(f"/analysis?account={account_id}&view=month")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        import re as _re
        match = _re.search(r"var chart4_data = (\{.*?\});", html, _re.DOTALL)
        self.assertIsNone(match, "chart4 should not be rendered when there is no balance data")

    def test_analysis_chart4_all_accounts_sums_balances(self) -> None:
        """chart4 with account=ALL sums balances across all accounts for the same date."""
        acc1 = self._insert_account("ACC1", 0.0)
        acc2 = self._insert_account("ACC2", 0.0)
        self._insert_balance("2026-01-15", acc1, 5000.0)
        self._insert_balance("2026-01-15", acc2, 3000.0)
        self._insert_balance("2026-01-20", acc1, 5200.0)

        response = self.client.get("/analysis?account=ALL&view=ytd")
        self.assertEqual(response.status_code, 200)
        chart4 = self._extract_chart(response.get_data(as_text=True), 4)

        dates = chart4["data"][0]["x"]
        values = {d: float(v) for d, v in zip(dates, chart4["data"][0]["y"])}

        self.assertAlmostEqual(values["2026-01-15"], 8000.0)
        self.assertAlmostEqual(values["2026-01-20"], 5200.0)

    def test_analysis_chart7_null_when_no_win_loss_pairs(self) -> None:
        """chart7 requires both wins and losses to compute a ratio. Absent losses → no chart7."""
        account_id = self._insert_account("WINONLY", 0.0)
        # Insert only winning trades (sell > buy) — avg_loss will be None → no ratio points
        self._insert_closed_trade(
            trade_code="WIN-1",
            account_id=account_id,
            created_at="2026-02-03 10:00:00",
            closed_at="2026-02-03",
            buy_price=100,
            sell_price=150,
        )
        self._insert_closed_trade(
            trade_code="WIN-2",
            account_id=account_id,
            created_at="2026-02-10 10:00:00",
            closed_at="2026-02-10",
            buy_price=100,
            sell_price=130,
        )

        response = self.client.get(f"/analysis?account={account_id}&view=ytd")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        import re as _re
        match = _re.search(r"var chart7_data = (\{.*?\});", html, _re.DOTALL)
        self.assertIsNone(match, "chart7 should be absent when there are no win/loss ratio pairs")

    def test_analysis_renders_with_empty_database(self) -> None:
        """No data in DB should still render the analysis page (all charts null, no 500)."""
        response = self.client.get("/analysis")
        self.assertEqual(response.status_code, 200)

    def test_analysis_defaults_to_month_view(self) -> None:
        """Omitting the ?view param should produce a valid month-view page."""
        account_id = self._insert_account("DEF", 0.0)
        response = self.client.get(f"/analysis?account={account_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"analysis", response.data.lower())

    def test_analysis_invalid_view_falls_back_to_month(self) -> None:
        """An unrecognised ?view value should fall back to the month view (not crash)."""
        response = self.client.get("/analysis?view=bogus")
        self.assertEqual(response.status_code, 200)

    def test_analysis_chart2_all_losers_yields_zero_win_pct(self) -> None:
        """When every trade on a day is a loss, chart2 win % should be 0."""
        account_id = self._insert_account("LOSE", 0.0)
        today = date.today()
        day = f"{today.year}-{today.month:02d}-05"
        self._insert_closed_trade(
            trade_code="LOSE-1",
            account_id=account_id,
            created_at=f"{day} 10:00:00",
            closed_at=day,
            buy_price=100,
            sell_price=80,
        )
        self._insert_closed_trade(
            trade_code="LOSE-2",
            account_id=account_id,
            created_at=f"{day} 11:00:00",
            closed_at=day,
            buy_price=100,
            sell_price=70,
        )

        response = self.client.get(f"/analysis?account={account_id}&view=month")
        self.assertEqual(response.status_code, 200)
        chart2 = self._extract_chart(response.get_data(as_text=True), 2)
        win_pct_values = [float(v) for v in chart2["data"][0]["y"]]
        self.assertTrue(all(v == 0.0 for v in win_pct_values), f"Expected all zeros, got {win_pct_values}")

    def test_analysis_chart8_excludes_weekend_dates(self) -> None:
        """chart8 only tracks Mon–Fri; weekend trade dates must not affect totals."""
        account_id = self._insert_account("WKND", 0.0)
        # 2026-03-01 is a Sunday; should be ignored by chart8
        self._insert_closed_trade(
            trade_code="WKND-SUN",
            account_id=account_id,
            created_at="2026-03-01 10:00:00",
            closed_at="2026-03-01",
            buy_price=100,
            sell_price=200,
        )
        # 2026-03-02 is Monday; should appear in chart8
        self._insert_closed_trade(
            trade_code="WKND-MON",
            account_id=account_id,
            created_at="2026-03-02 10:00:00",
            closed_at="2026-03-02",
            buy_price=100,
            sell_price=150,
        )

        # Query March 2026 month view
        response = self.client.get(f"/analysis?account={account_id}&view=month")
        self.assertEqual(response.status_code, 200)
        chart8 = self._extract_chart(response.get_data(as_text=True), 8)

        labels = chart8["data"][0]["x"]
        values = {label: float(v) for label, v in zip(labels, chart8["data"][0]["y"])}

        # Monday should contain the $50 (150-100) gain only
        self.assertAlmostEqual(values["Mon"], 50.0)
        # Total across all named days should equal 50 (Sunday excluded)
        self.assertAlmostEqual(sum(values.values()), 50.0)

    def test_save_analysis_preferences_valid_payload(self) -> None:
        """POST /analysis/preferences with valid JSON should return ok=True."""
        payload = {
            "order": ["chart1", "chart2", "chart3"],
            "visible": {"chart1": True, "chart2": False, "chart3": True},
        }
        response = self.client.post(
            "/analysis/preferences",
            json=payload,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body.get("ok"))

    def test_save_analysis_preferences_invalid_payload(self) -> None:
        """POST /analysis/preferences with wrong types should return 400."""
        response = self.client.post(
            "/analysis/preferences",
            json={"order": "not-a-list", "visible": []},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        body = response.get_json()
        self.assertFalse(body.get("ok"))

    def test_save_analysis_preferences_persisted_across_requests(self) -> None:
        """Preferences saved via POST should be reflected in the next GET /analysis."""
        payload = {
            "order": ["chart2", "chart1"],
            "visible": {"chart1": False, "chart2": True},
        }
        save_resp = self.client.post("/analysis/preferences", json=payload)
        self.assertEqual(save_resp.status_code, 200)

        get_resp = self.client.get("/analysis")
        self.assertEqual(get_resp.status_code, 200)

    def test_monthly_pnl_comparison_aggregates_all_accounts(self) -> None:
        zero_fee_account = self._insert_account("ZERO", 0.0)
        standard_fee_account = self._insert_account("STD", 0.65)

        self._insert_closed_trade(
            trade_code="ZERO-1",
            account_id=zero_fee_account,
            created_at="2026-01-03 10:00:00",
            closed_at="2026-01-03",
            buy_price=100,
            sell_price=200,
        )
        self._insert_closed_trade(
            trade_code="ZERO-2",
            account_id=zero_fee_account,
            created_at="2026-02-05 10:00:00",
            closed_at="2026-02-05",
            buy_price=100,
            sell_price=130,
        )
        self._insert_closed_trade(
            trade_code="STD-1",
            account_id=standard_fee_account,
            created_at="2026-01-11 10:00:00",
            closed_at="2026-01-11",
            buy_price=100,
            sell_price=120,
        )

        response = self.client.get("/analysis?account=ALL&view=ytd")
        self.assertEqual(response.status_code, 200)

        chart3 = self._extract_chart(response.get_data(as_text=True), 3)
        monthly = self._monthly_values(chart3)

        self.assertAlmostEqual(monthly["Jan 2026"], 118.7)
        self.assertAlmostEqual(monthly["Feb 2026"], 30.0)


if __name__ == "__main__":
    unittest.main()
