from __future__ import annotations

from datetime import date

from flask import redirect, render_template, request, url_for


def register_trade_routes(
    app,
    get_db,
    fetch_entries,
    compute_trade_stats,
    now_iso_date,
    now_iso_dt,
    generate_trade_code,
) -> None:
    @app.route("/trade/create", methods=["POST"])
    def create_trade():
        trade_code = request.form.get("trade_code", "").strip()
        symbol = request.form.get("symbol", "").strip().upper()
        option_type_raw = request.form.get("option_type", "CALL").strip().upper()
        account_id_raw = request.form.get("account_id", "").strip()
        expiration_raw = request.form.get("expiration", "").strip()
        strike_raw = request.form.get("strike", "").strip()

        if not symbol:
            return redirect(url_for("index"))

        if not trade_code:
            trade_code = generate_trade_code()

        option_type = "PUT" if option_type_raw == "PUT" else "CALL"

        account_id = None
        if account_id_raw:
            try:
                account_id = int(account_id_raw)
            except ValueError:
                return redirect(url_for("index"))

        expiration = expiration_raw or None

        strike = None
        if strike_raw:
            try:
                strike = float(strike_raw)
            except ValueError:
                return redirect(url_for("index"))

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO trades (trade_code, symbol, option_type, status, created_at, account_id, expiration, strike)
                VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?)
                """,
                (trade_code, symbol, option_type, now_iso_dt(), account_id, expiration, strike),
            )
            trade_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        return redirect(url_for("trade_detail", trade_id=trade_id))

    @app.route("/trade/<int:trade_id>")
    def trade_detail(trade_id: int):
        with get_db() as conn:
            trade = conn.execute(
                """
                SELECT trades.*, accounts.short_name AS account_short, accounts.full_name AS account_full,
                       accounts.fee_per_contract AS account_fee
                FROM trades
                LEFT JOIN accounts ON accounts.id = trades.account_id
                WHERE trades.id = ?
                """,
                (trade_id,),
            ).fetchone()
            if not trade:
                return redirect(url_for("index"))

            entries = fetch_entries(conn, trade_id)

        fee_per_contract = trade["account_fee"]
        if fee_per_contract is None:
            fee_per_contract = 0.65
        stats = compute_trade_stats(entries, fee_per_contract)
        open_contracts = stats["buy_contracts"] - stats["sell_contracts"]

        return render_template(
            "trade.html",
            trade=trade,
            entries=entries,
            stats=stats,
            open_contracts=open_contracts,
            fee_per_contract=fee_per_contract,
        )

    @app.route("/trade/<int:trade_id>/entry", methods=["POST"])
    def add_entry(trade_id: int):
        side_raw = request.form.get("side", "").strip().upper()
        side = "BUY" if side_raw == "BUY" else "SELL"

        try:
            contracts = int(request.form.get("contracts", "0"))
            price = float(request.form.get("price", "0"))
        except ValueError:
            return redirect(url_for("trade_detail", trade_id=trade_id))

        if contracts <= 0 or price <= 0:
            return redirect(url_for("trade_detail", trade_id=trade_id))

        with get_db() as conn:
            conn.execute(
                "INSERT INTO entries (trade_id, side, contracts, price, created_at) VALUES (?, ?, ?, ?, ?)",
                (trade_id, side, contracts, price, now_iso_dt()),
            )

        return redirect(url_for("trade_detail", trade_id=trade_id))

    @app.route("/entry/<int:entry_id>/update", methods=["POST"])
    def update_entry(entry_id: int):
        side_raw = request.form.get("side", "").strip().upper()
        side = "BUY" if side_raw == "BUY" else "SELL"

        try:
            contracts = int(request.form.get("contracts", "0"))
            price = float(request.form.get("price", "0"))
            trade_id = int(request.form.get("trade_id", "0"))
        except ValueError:
            return redirect(url_for("index"))

        if contracts <= 0 or price <= 0:
            return redirect(url_for("trade_detail", trade_id=trade_id))

        with get_db() as conn:
            entry = conn.execute(
                "SELECT id, trade_id FROM entries WHERE id = ?", (entry_id,)
            ).fetchone()
            if not entry:
                return redirect(url_for("index"))

            conn.execute(
                "UPDATE entries SET side = ?, contracts = ?, price = ? WHERE id = ?",
                (side, contracts, price, entry_id),
            )

        return redirect(url_for("trade_detail", trade_id=entry["trade_id"]))

    @app.route("/entry/<int:entry_id>/delete", methods=["POST"])
    def delete_entry(entry_id: int):
        with get_db() as conn:
            entry = conn.execute(
                "SELECT id, trade_id FROM entries WHERE id = ?",
                (entry_id,),
            ).fetchone()
            if not entry:
                return redirect(url_for("index"))

            conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))

        return redirect(url_for("trade_detail", trade_id=entry["trade_id"]))

    @app.route("/trade/<int:trade_id>/close", methods=["POST"])
    def close_trade(trade_id: int):
        notes = request.form.get("notes", "").strip()

        with get_db() as conn:
            trade = conn.execute(
                """
                SELECT trades.*, accounts.fee_per_contract AS account_fee
                FROM trades
                LEFT JOIN accounts ON accounts.id = trades.account_id
                WHERE trades.id = ?
                """,
                (trade_id,),
            ).fetchone()
            if not trade:
                return redirect(url_for("index"))

            if trade["status"] == "CLOSED":
                return redirect(url_for("trade_detail", trade_id=trade_id))

            entries = fetch_entries(conn, trade_id)
            fee_per_contract = trade["account_fee"]
            if fee_per_contract is None:
                fee_per_contract = 0.65
            stats = compute_trade_stats(entries, fee_per_contract)
            open_contracts = stats["buy_contracts"] - stats["sell_contracts"]
            if open_contracts != 0:
                return redirect(url_for("trade_detail", trade_id=trade_id))

            conn.execute(
                "UPDATE trades SET status = 'CLOSED', closed_at = ?, notes = ? WHERE id = ?",
                (now_iso_date(), notes, trade_id),
            )

        return redirect(url_for("month_summary", year=date.today().year, month=date.today().month))

    @app.route("/trade/<int:trade_id>/save-open", methods=["POST"])
    def save_trade_open(trade_id: int):
        notes = request.form.get("notes", "").strip()

        with get_db() as conn:
            trade = conn.execute(
                "SELECT id FROM trades WHERE id = ?",
                (trade_id,),
            ).fetchone()
            if not trade:
                return redirect(url_for("index"))

            conn.execute(
                "UPDATE trades SET notes = ? WHERE id = ?",
                (notes, trade_id),
            )

        return redirect(url_for("index"))

    @app.route("/trade/<int:trade_id>/duplicate", methods=["POST"])
    def duplicate_trade(trade_id: int):
        with get_db() as conn:
            source_trade = conn.execute(
                """
                SELECT symbol, option_type, account_id, expiration, strike
                FROM trades
                WHERE id = ?
                """,
                (trade_id,),
            ).fetchone()
            if not source_trade:
                return redirect(url_for("index"))

            trade_code = generate_trade_code()
            conn.execute(
                """
                INSERT INTO trades (trade_code, symbol, option_type, status, created_at, account_id, expiration, strike)
                VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?)
                """,
                (
                    trade_code,
                    source_trade["symbol"],
                    source_trade["option_type"],
                    now_iso_dt(),
                    source_trade["account_id"],
                    source_trade["expiration"],
                    source_trade["strike"],
                ),
            )
            new_trade_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        return redirect(url_for("trade_detail", trade_id=new_trade_id))

    @app.route("/trade/<int:trade_id>/delete", methods=["POST"])
    def delete_trade(trade_id: int):
        return_view = request.form.get("return_view", "").strip()
        return_year_raw = request.form.get("return_year", "").strip()
        return_month_raw = request.form.get("return_month", "").strip()
        return_account_raw = request.form.get("return_account", "").strip()

        with get_db() as conn:
            trade = conn.execute("SELECT id FROM trades WHERE id = ?", (trade_id,)).fetchone()
            if not trade:
                return redirect(url_for("index"))

            conn.execute("DELETE FROM entries WHERE trade_id = ?", (trade_id,))
            conn.execute("DELETE FROM journal WHERE trade_id = ?", (trade_id,))
            conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))

        if return_view == "month":
            try:
                year = int(return_year_raw)
                month = int(return_month_raw)
            except ValueError:
                return redirect(url_for("index"))

            if return_account_raw:
                try:
                    account_id = int(return_account_raw)
                except ValueError:
                    account_id = None
                if account_id is not None:
                    return redirect(url_for("month_summary", year=year, month=month, account=account_id))

            return redirect(url_for("month_summary", year=year, month=month))

        return redirect(url_for("index"))
