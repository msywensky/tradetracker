from __future__ import annotations

from flask import jsonify, render_template, request

from tracker.services import anthropic_client
from tracker.services.anthropic_client import (
    AnthropicConfigError,
    AnthropicExtractionError,
)


def register_import_routes(
    app,
    get_db,
    build_preview,
    now_iso_dt,
    now_iso_date,
    generate_trade_code,
) -> None:
    @app.route("/import")
    def import_page():
        with get_db() as conn:
            accounts = conn.execute(
                "SELECT * FROM accounts ORDER BY short_name"
            ).fetchall()
        return render_template("import.html", accounts=accounts)

    @app.route("/import/screenshot/extract", methods=["POST"])
    def import_screenshot_extract():
        payload = request.get_json(silent=True) or {}
        image_b64 = payload.get("image")
        media_type = payload.get("media_type")
        if not image_b64 or not media_type:
            return jsonify({"error": "Missing image data."}), 400

        try:
            extraction = anthropic_client.extract_fills_from_image(image_b64, media_type)
        except AnthropicConfigError as exc:
            return jsonify({"error": str(exc)}), 400
        except AnthropicExtractionError as exc:
            return jsonify({"error": str(exc)}), 502

        with get_db() as conn:
            accounts = conn.execute(
                "SELECT * FROM accounts ORDER BY short_name"
            ).fetchall()

        trades = build_preview(extraction.get("fills", []), accounts)
        return jsonify({"trades": trades})

    @app.route("/import/screenshot/commit", methods=["POST"])
    def import_screenshot_commit():
        payload = request.get_json(silent=True) or {}
        trades = payload.get("trades")
        if not isinstance(trades, list) or not trades:
            return jsonify({"error": "No trades to import."}), 400

        inserted = 0
        with get_db() as conn:
            for trade in trades:
                if not isinstance(trade, dict):
                    continue

                symbol = str(trade.get("symbol", "")).strip().upper()
                entries = trade.get("entries")
                if not symbol or not isinstance(entries, list) or not entries:
                    continue

                option_type = "PUT" if str(trade.get("option_type", "")).strip().upper() == "PUT" else "CALL"

                account_id = trade.get("account_id")
                if account_id is not None:
                    try:
                        account_id = int(account_id)
                    except (TypeError, ValueError):
                        account_id = None

                strike = trade.get("strike")
                if strike is not None:
                    try:
                        strike = float(strike)
                    except (TypeError, ValueError):
                        strike = None

                expiration = trade.get("expiration") or None
                notes = str(trade.get("notes") or "").strip()
                created_at = str(trade.get("created_at") or now_iso_dt())

                valid_entries = []
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    side = "BUY" if str(entry.get("side", "")).strip().upper() == "BUY" else "SELL"
                    try:
                        contracts = int(entry.get("contracts"))
                        price = float(entry.get("price"))
                    except (TypeError, ValueError):
                        continue
                    if contracts <= 0 or price <= 0:
                        continue
                    valid_entries.append(
                        (side, contracts, price, str(entry.get("created_at") or created_at))
                    )

                if not valid_entries:
                    continue

                net = sum(c if s == "BUY" else -c for s, c, _, _ in valid_entries)
                status = "OPEN" if net != 0 else "CLOSED"
                closed_at = now_iso_date() if status == "CLOSED" else None

                conn.execute(
                    """
                    INSERT INTO trades (trade_code, symbol, option_type, status, created_at, closed_at, account_id, expiration, strike, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        generate_trade_code(),
                        symbol,
                        option_type,
                        status,
                        created_at,
                        closed_at,
                        account_id,
                        expiration,
                        strike,
                        notes or None,
                    ),
                )
                trade_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

                for side, contracts, price, entry_created_at in valid_entries:
                    conn.execute(
                        "INSERT INTO entries (trade_id, side, contracts, price, created_at) VALUES (?, ?, ?, ?, ?)",
                        (trade_id, side, contracts, price, entry_created_at),
                    )
                inserted += 1

        return jsonify({"ok": True, "inserted": inserted})
