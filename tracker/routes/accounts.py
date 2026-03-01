from __future__ import annotations

from flask import redirect, render_template, request, session, url_for


def register_account_routes(app, get_db) -> None:
    @app.route("/accounts")
    def accounts_page():
        account_error = request.args.get("account_error", "").strip()

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

        return render_template(
            "accounts.html",
            accounts=accounts,
            account_error=account_error,
            default_account_id=default_account_id,
        )

    @app.route("/account/create", methods=["POST"])
    def create_account():
        short_name = request.form.get("short_name", "").strip().upper()
        full_name = request.form.get("full_name", "").strip()
        fee_str = request.form.get("fee_per_contract", "").strip()

        try:
            fee_per_contract = float(fee_str)
        except ValueError:
            return redirect(url_for("accounts_page"))

        if not short_name or not full_name or fee_per_contract < 0:
            return redirect(url_for("accounts_page"))

        with get_db() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO accounts (short_name, full_name, fee_per_contract)
                VALUES (?, ?, ?)
                """,
                (short_name, full_name, fee_per_contract),
            )

        return redirect(url_for("accounts_page"))

    @app.route("/account/<int:account_id>/update", methods=["POST"])
    def update_account(account_id: int):
        short_name = request.form.get("short_name", "").strip().upper()
        full_name = request.form.get("full_name", "").strip()
        fee_str = request.form.get("fee_per_contract", "").strip()

        try:
            fee_per_contract = float(fee_str)
        except ValueError:
            return redirect(url_for("accounts_page"))

        if not short_name or not full_name or fee_per_contract < 0:
            return redirect(url_for("accounts_page"))

        with get_db() as conn:
            conn.execute(
                """
                UPDATE accounts
                SET short_name = ?, full_name = ?, fee_per_contract = ?
                WHERE id = ?
                """,
                (short_name, full_name, fee_per_contract, account_id),
            )

        return redirect(url_for("accounts_page"))

    @app.route("/account/<int:account_id>/delete", methods=["POST"])
    def delete_account(account_id: int):
        with get_db() as conn:
            trade_count = conn.execute(
                "SELECT COUNT(*) AS total FROM trades WHERE account_id = ?",
                (account_id,),
            ).fetchone()["total"]
            if trade_count:
                return redirect(
                    url_for(
                        "accounts_page",
                        account_error="Account has associated trades and cannot be deleted.",
                    )
                )

            conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            conn.execute("DELETE FROM daily_balances WHERE account_id = ?", (account_id,))
            conn.execute(
                "DELETE FROM app_settings WHERE key = 'default_account_id' AND value = ?",
                (str(account_id),),
            )

        if session.get("selected_account_id") == account_id:
            session.pop("selected_account_id", None)

        return redirect(url_for("accounts_page"))

    @app.route("/account/<int:account_id>/set-default", methods=["POST"])
    def set_default_account(account_id: int):
        with get_db() as conn:
            account = conn.execute("SELECT id FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if not account:
                return redirect(url_for("accounts_page"))

            conn.execute(
                """
                INSERT INTO app_settings (key, value)
                VALUES ('default_account_id', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(account_id),),
            )

        session["selected_account_id"] = account_id

        return redirect(url_for("accounts_page"))
