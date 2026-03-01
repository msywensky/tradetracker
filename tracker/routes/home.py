from __future__ import annotations

from datetime import date

from flask import render_template, session


def register_home_routes(app, get_db) -> None:
    @app.route("/")
    def index():
        today_iso = date.today().isoformat()
        with get_db() as conn:
            accounts = conn.execute(
                "SELECT * FROM accounts ORDER BY short_name"
            ).fetchall()
            account_ids = {row["id"] for row in accounts}

            default_account_row = conn.execute(
                "SELECT value FROM app_settings WHERE key = 'default_account_id'"
            ).fetchone()
            default_account_id = None
            if default_account_row:
                try:
                    parsed_default = int(default_account_row["value"])
                except (TypeError, ValueError):
                    parsed_default = None
                if parsed_default in account_ids:
                    default_account_id = parsed_default

            selected_account_id = None
            session_selected = session.get("selected_account_id")
            if isinstance(session_selected, int) and session_selected in account_ids:
                selected_account_id = session_selected
            elif default_account_id is not None:
                selected_account_id = default_account_id

            if selected_account_id is not None:
                session["selected_account_id"] = selected_account_id
            else:
                session.pop("selected_account_id", None)

            open_trades = conn.execute(
                """
                SELECT
                    trades.*,
                    accounts.short_name AS account_short,
                    COALESCE(SUM(CASE WHEN entries.side = 'BUY' THEN entries.contracts ELSE 0 END), 0) AS buy_contracts,
                    COALESCE(SUM(CASE WHEN entries.side = 'SELL' THEN entries.contracts ELSE 0 END), 0) AS sell_contracts,
                    COALESCE(
                        ROUND(
                            SUM(CASE WHEN entries.side = 'BUY' THEN entries.contracts * entries.price ELSE 0 END) * 1.0
                            / NULLIF(SUM(CASE WHEN entries.side = 'BUY' THEN entries.contracts ELSE 0 END), 0),
                            2
                        ),
                        0
                    ) AS avg_buy_price,
                    COALESCE(
                        ROUND(
                            SUM(CASE WHEN entries.side = 'SELL' THEN entries.contracts * entries.price ELSE 0 END) * 1.0
                            / NULLIF(SUM(CASE WHEN entries.side = 'SELL' THEN entries.contracts ELSE 0 END), 0),
                            2
                        ),
                        0
                    ) AS avg_sell_price
                FROM trades
                LEFT JOIN accounts ON accounts.id = trades.account_id
                LEFT JOIN entries ON entries.trade_id = trades.id
                WHERE trades.status = 'OPEN'
                GROUP BY trades.id
                ORDER BY trades.created_at DESC
                """
            ).fetchall()
            closed_trades = conn.execute(
                """
                SELECT trades.*, accounts.short_name AS account_short
                FROM trades
                LEFT JOIN accounts ON accounts.id = trades.account_id
                WHERE trades.status = 'CLOSED' AND trades.closed_at = ?
                ORDER BY trades.closed_at DESC
                LIMIT 20
                """,
                (today_iso,),
            ).fetchall()
            recent_balances = conn.execute(
                """
                SELECT d.date, d.balance, a.short_name AS account_short
                FROM daily_balances d
                LEFT JOIN accounts a ON a.id = d.account_id
                ORDER BY d.date DESC, a.short_name ASC
                LIMIT 20
                """
            ).fetchall()

        return render_template(
            "index.html",
            open_trades=open_trades,
            closed_trades=closed_trades,
            recent_balances=recent_balances,
            accounts=accounts,
            today=date.today(),
            selected_account_id=selected_account_id,
            default_account_id=default_account_id,
        )

    @app.route("/journal")
    def journal_page():
        today = date.today()  # Pass as date object, not string
        month_start = today.replace(day=1)
        with get_db() as conn:
            closed_trades_today = conn.execute(
                '''
                SELECT t.id, t.trade_code, t.symbol, t.option_type,
                       (SELECT SUM(CASE WHEN e.side = "BUY" THEN e.contracts ELSE 0 END) FROM entries e WHERE e.trade_id = t.id) AS num_options,
                       (SELECT SUM(CASE WHEN e.side = "SELL" THEN e.contracts * e.price ELSE 0 END) - SUM(CASE WHEN e.side = "BUY" THEN e.contracts * e.price ELSE 0 END) FROM entries e WHERE e.trade_id = t.id) AS pnl
                FROM trades t
                WHERE t.status = "CLOSED" AND t.closed_at = ?
                ORDER BY t.closed_at DESC
                ''',
                (today.isoformat(),)
            ).fetchall()
            # Fetch journal entries and join trade info if linked
            journal_entries = conn.execute('''
                SELECT j.*, t.symbol, t.option_type, 
                       (SELECT SUM(CASE WHEN e.side = "BUY" THEN e.contracts ELSE 0 END) FROM entries e WHERE e.trade_id = t.id) AS num_options,
                       (SELECT SUM(CASE WHEN e.side = "SELL" THEN e.contracts * e.price ELSE 0 END) - SUM(CASE WHEN e.side = "BUY" THEN e.contracts * e.price ELSE 0 END) FROM entries e WHERE e.trade_id = t.id) AS pnl,
                       t.trade_code
                FROM journal j
                LEFT JOIN trades t ON j.trade_id = t.id
                ORDER BY j.date DESC
            ''').fetchall()
        return render_template(
            'journal.html',
            today=today,
            month_start=month_start,
            closed_trades_today=closed_trades_today,
            journal_entries=journal_entries
        )
