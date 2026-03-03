from __future__ import annotations

from datetime import date, datetime, timedelta
from math import sqrt
from statistics import median
import json

from flask import jsonify, redirect, render_template, request, session, url_for
import plotly.graph_objects as go
import plotly.utils as pu


def register_report_routes(app, get_db, fetch_entries, compute_trade_stats) -> None:
    ANALYSIS_PREFS_KEY = "analysis_chart_preferences"
    ANALYSIS_ALLOWED_CHART_IDS = {f"chart{idx}" for idx in range(1, 9)}

    def resolve_selected_account_id(conn, accounts, account_arg: str | None) -> int | None:
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

        if account_arg is not None:
            normalized = account_arg.strip()
            if normalized.upper() == "ALL":
                session.pop("selected_account_id", None)
                return None
            try:
                query_account_id = int(normalized)
            except ValueError:
                query_account_id = None
            if query_account_id in account_ids:
                session["selected_account_id"] = query_account_id
                return query_account_id

        session_selected = session.get("selected_account_id")
        if isinstance(session_selected, int) and session_selected in account_ids:
            return session_selected

        if default_account_id is not None:
            session["selected_account_id"] = default_account_id
            return default_account_id

        session.pop("selected_account_id", None)
        return None

    @app.route("/month/<int:year>/<int:month>")
    def month_summary(year: int, month: int):
        month_start = date(year, month, 1)
        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)

        account_arg = request.args.get("account")

        with get_db() as conn:
            accounts = conn.execute(
                "SELECT * FROM accounts ORDER BY short_name"
            ).fetchall()
            account_id = resolve_selected_account_id(conn, accounts, account_arg)

            balances = {}
            if account_id is not None:
                balance_rows = conn.execute(
                    """
                    SELECT date, balance FROM daily_balances
                    WHERE date >= ? AND date < ? AND account_id = ?
                    ORDER BY date DESC
                    """,
                    (month_start.isoformat(), next_month.isoformat(), account_id),
                ).fetchall()
                balances = {row["date"]: row["balance"] for row in balance_rows}

            trade_query = [
                "SELECT trades.*, accounts.short_name AS account_short, accounts.fee_per_contract AS account_fee",
                "FROM trades",
                "LEFT JOIN accounts ON accounts.id = trades.account_id",
                "WHERE trades.status = 'CLOSED' AND trades.closed_at >= ? AND trades.closed_at < ?",
            ]
            trade_params = [month_start.isoformat(), next_month.isoformat()]
            if account_id is not None:
                trade_query.append("AND trades.account_id = ?")
                trade_params.append(account_id)
            trade_query.append("ORDER BY trades.closed_at DESC")
            closed_trades = conn.execute(" ".join(trade_query), trade_params).fetchall()

            trade_rows = []
            today_trade_rows = []
            daily_rows: dict[str, dict] = {}
            month_wins = 0
            month_losses = 0
            month_pnl = 0
            month_fees = 0
            month_winning_pnl = 0
            month_losing_pnl = 0

            for trade in closed_trades:
                entries = fetch_entries(conn, trade["id"])
                fee_per_contract = trade["account_fee"]
                if fee_per_contract is None:
                    fee_per_contract = 0.65
                stats = compute_trade_stats(entries, fee_per_contract)
                close_date = trade["closed_at"]

                trade_rows.append({
                    "trade": trade,
                    "stats": stats,
                })

                if close_date == date.today().isoformat():
                    today_trade_rows.append({
                        "trade": trade,
                        "stats": stats,
                    })

                month_pnl += stats["pnl_after"]
                month_fees += stats["fees"]
                if stats["pnl_after"] > 0:
                    month_wins += 1
                    month_winning_pnl += stats["pnl_after"]
                elif stats["pnl_after"] < 0:
                    month_losses += 1
                    month_losing_pnl += stats["pnl_after"]

                day_row = daily_rows.setdefault(
                    close_date,
                    {
                        "date": close_date,
                        "trade_count": 0,
                        "total_contracts": 0,
                        "pnl_before": 0,
                        "fees": 0,
                        "pnl_after": 0,
                        "winning_pnl": 0,
                        "losing_pnl": 0,
                        "win_trades": 0,
                        "lose_trades": 0,
                        "balance": balances.get(close_date),
                    },
                )

                day_row["trade_count"] += 1
                day_row["total_contracts"] += stats["total_contracts"]
                day_row["pnl_before"] += stats["pnl_before"]
                day_row["fees"] += stats["fees"]
                day_row["pnl_after"] += stats["pnl_after"]
                if stats["pnl_after"] > 0:
                    day_row["win_trades"] += 1
                    day_row["winning_pnl"] += stats["pnl_after"]
                elif stats["pnl_after"] < 0:
                    day_row["lose_trades"] += 1
                    day_row["losing_pnl"] += stats["pnl_after"]

            for balance_date, balance_value in balances.items():
                if balance_date not in daily_rows:
                    daily_rows[balance_date] = {
                        "date": balance_date,
                        "trade_count": 0,
                        "total_contracts": 0,
                        "pnl_before": 0,
                        "fees": 0,
                        "pnl_after": 0,
                        "winning_pnl": 0,
                        "losing_pnl": 0,
                        "win_trades": 0,
                        "lose_trades": 0,
                        "balance": balance_value,
                    }

            daily_list = sorted(daily_rows.values(), key=lambda row: row["date"])
            running_total = 0
            for row in daily_list:
                running_total += row["pnl_after"]
                row["running_total"] = running_total

            daily_pnls = [row["pnl_after"] for row in daily_list]
            daily_avg = (sum(daily_pnls) / len(daily_pnls)) if daily_pnls else 0
            daily_median = median(daily_pnls) if daily_pnls else 0
            total_trades = month_wins + month_losses
            win_pct = (month_wins / total_trades * 100) if total_trades else 0
            month_stats = {
                "wins": month_wins,
                "losses": month_losses,
                "win_pct": win_pct,
                "total_pnl": month_pnl,
                "total_fees": month_fees,
                "daily_avg": daily_avg,
                "daily_median": daily_median,
                "winning_pnl": month_winning_pnl,
                "losing_pnl": month_losing_pnl,
            }

        return render_template(
            "month.html",
            today_trade_rows=today_trade_rows,
            trade_rows=trade_rows,
            daily_rows=daily_list,
            daily_dict=daily_rows,
            month_stats=month_stats,
            month_start=month_start,
            accounts=accounts,
            selected_account=account_id,
        )

    @app.route("/ytd/<int:year>")
    def ytd_summary(year: int):
        start_date = date(year, 1, 1)
        end_date = date.today() + timedelta(days=1)

        account_arg = request.args.get("account")

        with get_db() as conn:
            accounts = conn.execute(
                "SELECT * FROM accounts ORDER BY short_name"
            ).fetchall()
            account_id = resolve_selected_account_id(conn, accounts, account_arg)

            balances = {}
            if account_id is not None:
                balance_rows = conn.execute(
                    """
                    SELECT date, balance FROM daily_balances
                    WHERE date >= ? AND date < ? AND account_id = ?
                    """,
                    (start_date.isoformat(), end_date.isoformat(), account_id),
                ).fetchall()
                balances = {row["date"]: row["balance"] for row in balance_rows}

            trade_query = [
                "SELECT trades.*, accounts.short_name AS account_short, accounts.fee_per_contract AS account_fee",
                "FROM trades",
                "LEFT JOIN accounts ON accounts.id = trades.account_id",
                "WHERE trades.status = 'CLOSED' AND trades.closed_at >= ? AND trades.closed_at < ?",
            ]
            trade_params = [start_date.isoformat(), end_date.isoformat()]
            if account_id is not None:
                trade_query.append("AND trades.account_id = ?")
                trade_params.append(account_id)
            trade_query.append("ORDER BY trades.closed_at ASC")
            closed_trades = conn.execute(" ".join(trade_query), trade_params).fetchall()

            trade_rows = []
            daily_rows: dict[str, dict] = {}
            ytd_wins = 0
            ytd_losses = 0
            ytd_pnl = 0
            ytd_fees = 0
            ytd_winning_pnl = 0
            ytd_losing_pnl = 0

            for trade in closed_trades:
                entries = fetch_entries(conn, trade["id"])
                fee_per_contract = trade["account_fee"]
                if fee_per_contract is None:
                    fee_per_contract = 0.65
                stats = compute_trade_stats(entries, fee_per_contract)
                close_date = trade["closed_at"]

                trade_rows.append({
                    "trade": trade,
                    "stats": stats,
                })

                ytd_pnl += stats["pnl_after"]
                ytd_fees += stats["fees"]
                if stats["pnl_after"] > 0:
                    ytd_wins += 1
                    ytd_winning_pnl += stats["pnl_after"]
                elif stats["pnl_after"] < 0:
                    ytd_losses += 1
                    ytd_losing_pnl += stats["pnl_after"]

                day_row = daily_rows.setdefault(
                    close_date,
                    {
                        "date": close_date,
                        "total_contracts": 0,
                        "pnl_before": 0,
                        "pnl_after": 0,
                        "win_trades": 0,
                        "lose_trades": 0,
                        "balance": balances.get(close_date),
                    },
                )

                day_row["total_contracts"] += stats["total_contracts"]
                day_row["pnl_before"] += stats["pnl_before"]
                day_row["pnl_after"] += stats["pnl_after"]
                if stats["pnl_after"] > 0:
                    day_row["win_trades"] += 1
                elif stats["pnl_after"] < 0:
                    day_row["lose_trades"] += 1

            for balance_date, balance_value in balances.items():
                if balance_date not in daily_rows:
                    daily_rows[balance_date] = {
                        "date": balance_date,
                        "total_contracts": 0,
                        "pnl_before": 0,
                        "pnl_after": 0,
                        "win_trades": 0,
                        "lose_trades": 0,
                        "balance": balance_value,
                    }

            daily_list = sorted(daily_rows.values(), key=lambda row: row["date"])
            running_total = 0
            for row in daily_list:
                running_total += row["pnl_after"]
                row["running_total"] = running_total

            daily_pnls = [row["pnl_after"] for row in daily_list]
            daily_avg = (sum(daily_pnls) / len(daily_pnls)) if daily_pnls else 0
            daily_median = median(daily_pnls) if daily_pnls else 0
            total_trades = ytd_wins + ytd_losses
            win_pct = (ytd_wins / total_trades * 100) if total_trades else 0
            ytd_stats = {
                "wins": ytd_wins,
                "losses": ytd_losses,
                "win_pct": win_pct,
                "total_pnl": ytd_pnl,
                "total_fees": ytd_fees,
                "daily_avg": daily_avg,
                "daily_median": daily_median,
                "winning_pnl": ytd_winning_pnl,
                "losing_pnl": ytd_losing_pnl,
            }

        return render_template(
            "ytd.html",
            trade_rows=trade_rows,
            daily_rows=daily_list,
            daily_dict=daily_rows,
            ytd_stats=ytd_stats,
            start_date=start_date,
            accounts=accounts,
            selected_account=account_id,
        )

    @app.route("/month/balance", methods=["POST"])
    def update_balance():
        date_str = request.form.get("date", "").strip()
        year_str = request.form.get("year", "").strip()
        month_str = request.form.get("month", "").strip()
        balance_str = request.form.get("balance", "").strip()
        account_str = request.form.get("account_id", "").strip()

        try:
            validated_date = date.fromisoformat(date_str)
            balance = float(balance_str)
            year = int(year_str)
            month = int(month_str)
            account_id = int(account_str)
        except ValueError:
            return redirect(url_for("index"))

        date_str = validated_date.isoformat()

        if balance < 0:
            return redirect(url_for("month_summary", year=year, month=month))

        with get_db() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO daily_balances (date, account_id, balance)
                VALUES (?, ?, ?)
                """,
                (date_str, account_id, balance),
            )

        return redirect(url_for("month_summary", year=year, month=month, account=account_id))

    @app.route("/balance/create", methods=["POST"])
    def create_balance():
        date_str = request.form.get("date", "").strip()
        account_str = request.form.get("account_id", "").strip()
        balance_str = request.form.get("balance", "").strip()

        try:
            parsed_date = date.fromisoformat(date_str)
            account_id = int(account_str)
            balance = float(balance_str)
        except ValueError:
            return redirect(url_for("index"))

        if balance < 0:
            return redirect(url_for("index"))

        with get_db() as conn:
            account = conn.execute("SELECT id FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if not account:
                return redirect(url_for("index"))

            conn.execute(
                """
                INSERT OR REPLACE INTO daily_balances (date, account_id, balance)
                VALUES (?, ?, ?)
                """,
                (parsed_date.isoformat(), account_id, balance),
            )

        return redirect(url_for("index", _anchor="balances"))

    @app.route("/analysis")
    def analysis():
        today = date.today()
        current_month = today.month
        current_year = today.year

        account_arg = request.args.get("account")

        view_type = request.args.get("view", "month")
        if view_type not in ["month", "ytd"]:
            view_type = "month"

        with get_db() as conn:
            accounts = conn.execute(
                "SELECT * FROM accounts ORDER BY short_name"
            ).fetchall()
            account_id = resolve_selected_account_id(conn, accounts, account_arg)

            prefs_row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?",
                (ANALYSIS_PREFS_KEY,),
            ).fetchone()
            chart_preferences = {}
            if prefs_row and prefs_row["value"]:
                try:
                    parsed_prefs = json.loads(prefs_row["value"])
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed_prefs = {}
                if isinstance(parsed_prefs, dict):
                    chart_preferences = parsed_prefs

            trade_query = [
                "SELECT trades.*, accounts.short_name AS account_short, accounts.fee_per_contract AS account_fee",
                "FROM trades",
                "LEFT JOIN accounts ON accounts.id = trades.account_id",
                "WHERE trades.status = 'CLOSED'",
            ]
            trade_params = []
            if account_id is not None:
                trade_query.append("AND trades.account_id = ?")
                trade_params.append(account_id)
            trade_query.append("ORDER BY trades.closed_at ASC")

            trades = conn.execute(" ".join(trade_query), trade_params).fetchall()

            monthly_data = {}
            current_month_daily = {}
            ytd_daily = {}

            for trade in trades:
                entries = fetch_entries(conn, trade["id"])
                fee = trade["account_fee"] if trade["account_fee"] is not None else 0.65
                stats = compute_trade_stats(entries, fee)

                close_date = datetime.fromisoformat(trade["closed_at"]).date()
                close_year = close_date.year
                close_month = close_date.month

                key = (close_year, close_month)
                if key not in monthly_data:
                    monthly_data[key] = {"pnl": 0, "wins": 0, "losses": 0}

                monthly_data[key]["pnl"] += stats["pnl_after"]
                if stats["pnl_after"] > 0:
                    monthly_data[key]["wins"] += 1
                elif stats["pnl_after"] < 0:
                    monthly_data[key]["losses"] += 1

                if close_year == current_year and close_month == current_month:
                    date_str = close_date.isoformat()
                    if date_str not in current_month_daily:
                        current_month_daily[date_str] = {
                            "pnl": 0,
                            "wins": 0,
                            "losses": 0,
                            "win_pnl": 0,
                            "loss_pnl_abs": 0,
                        }

                    current_month_daily[date_str]["pnl"] += stats["pnl_after"]
                    if stats["pnl_after"] > 0:
                        current_month_daily[date_str]["wins"] += 1
                        current_month_daily[date_str]["win_pnl"] += stats["pnl_after"]
                    elif stats["pnl_after"] < 0:
                        current_month_daily[date_str]["losses"] += 1
                        current_month_daily[date_str]["loss_pnl_abs"] += abs(stats["pnl_after"])

                if close_year == current_year:
                    date_str = close_date.isoformat()
                    if date_str not in ytd_daily:
                        ytd_daily[date_str] = {
                            "pnl": 0,
                            "wins": 0,
                            "losses": 0,
                            "win_pnl": 0,
                            "loss_pnl_abs": 0,
                        }

                    ytd_daily[date_str]["pnl"] += stats["pnl_after"]
                    if stats["pnl_after"] > 0:
                        ytd_daily[date_str]["wins"] += 1
                        ytd_daily[date_str]["win_pnl"] += stats["pnl_after"]
                    elif stats["pnl_after"] < 0:
                        ytd_daily[date_str]["losses"] += 1
                        ytd_daily[date_str]["loss_pnl_abs"] += abs(stats["pnl_after"])

            daily_data = current_month_daily if view_type == "month" else ytd_daily

            if daily_data:
                daily_dates = sorted(daily_data.keys())
                daily_pnls = [daily_data[d]["pnl"] for d in daily_dates]

                running_total = 0
                for pnl in daily_pnls:
                    running_total += pnl

                if view_type == "month":
                    title = f"Daily P&L Trend - {date(current_year, current_month, 1).strftime('%B %Y')}"
                else:
                    title = f"Daily P&L Trend - {current_year} YTD"

                chart1 = go.Figure()
                chart1.add_trace(go.Scatter(
                    x=daily_dates,
                    y=daily_pnls,
                    mode="lines+markers",
                    name="Daily P&L",
                    line=dict(color="#f08a24", width=2),
                    marker=dict(size=8),
                ))
                chart1.update_layout(
                    title=title,
                    xaxis_title="Date",
                    yaxis_title="P&L ($)",
                    hovermode="x unified",
                    template="plotly_white",
                    plot_bgcolor="#fffaf2",
                    paper_bgcolor="#f4efe7",
                    font=dict(family="Palatino, serif", color="#1b1b1f"),
                    showlegend=True,
                )

                chart1_json = json.dumps(chart1, cls=pu.PlotlyJSONEncoder)
            else:
                chart1_json = None

            if view_type == "month":
                win_pct_dates = sorted(current_month_daily.keys())
                win_pct_values = []
                for d in win_pct_dates:
                    wins = current_month_daily[d]["wins"]
                    losses = current_month_daily[d]["losses"]
                    total = wins + losses
                    win_pct_values.append((wins / total * 100) if total else 0)
                title = f"Win Percentage - {date(current_year, current_month, 1).strftime('%B %Y')}"
                x_values = win_pct_dates
                period_pnl_values = [current_month_daily[d]["pnl"] for d in win_pct_dates]
                period_trade_counts = [
                    current_month_daily[d]["wins"] + current_month_daily[d]["losses"]
                    for d in win_pct_dates
                ]
                period_ratio_values = []
                for d in win_pct_dates:
                    wins = current_month_daily[d]["wins"]
                    losses = current_month_daily[d]["losses"]
                    avg_win = (current_month_daily[d]["win_pnl"] / wins) if wins else None
                    avg_loss = (current_month_daily[d]["loss_pnl_abs"] / losses) if losses else None
                    if avg_win is not None and avg_loss not in (None, 0):
                        period_ratio_values.append(avg_win / avg_loss)
                    else:
                        period_ratio_values.append(None)
            else:
                weekly_data: dict[str, dict[str, int]] = {}
                for date_str, values in ytd_daily.items():
                    day_value = date.fromisoformat(date_str)
                    week_start = day_value - timedelta(days=day_value.weekday())
                    week_key = week_start.isoformat()
                    bucket = weekly_data.setdefault(
                        week_key,
                        {"wins": 0, "losses": 0, "pnl": 0, "win_pnl": 0, "loss_pnl_abs": 0},
                    )
                    bucket["wins"] += values["wins"]
                    bucket["losses"] += values["losses"]
                    bucket["pnl"] += values["pnl"]
                    bucket["win_pnl"] += values["win_pnl"]
                    bucket["loss_pnl_abs"] += values["loss_pnl_abs"]

                x_values = sorted(weekly_data.keys())
                win_pct_values = []
                for week_key in x_values:
                    wins = weekly_data[week_key]["wins"]
                    losses = weekly_data[week_key]["losses"]
                    total = wins + losses
                    win_pct_values.append((wins / total * 100) if total else 0)
                title = f"Win Percentage - {current_year} YTD (Weekly)"
                period_pnl_values = [weekly_data[week_key]["pnl"] for week_key in x_values]
                period_trade_counts = [
                    weekly_data[week_key]["wins"] + weekly_data[week_key]["losses"]
                    for week_key in x_values
                ]
                period_ratio_values = []
                for week_key in x_values:
                    wins = weekly_data[week_key]["wins"]
                    losses = weekly_data[week_key]["losses"]
                    avg_win = (weekly_data[week_key]["win_pnl"] / wins) if wins else None
                    avg_loss = (weekly_data[week_key]["loss_pnl_abs"] / losses) if losses else None
                    if avg_win is not None and avg_loss not in (None, 0):
                        period_ratio_values.append(avg_win / avg_loss)
                    else:
                        period_ratio_values.append(None)

            if x_values:
                chart2 = go.Figure()
                chart2.add_trace(go.Scatter(
                    x=x_values,
                    y=win_pct_values,
                    mode="lines+markers",
                    name="Win %",
                    line=dict(color="#4CAF50", width=2),
                    marker=dict(size=8),
                ))
                chart2.update_layout(
                    title=title,
                    xaxis_title="Date" if view_type == "month" else "Week",
                    yaxis_title="Win %",
                    yaxis=dict(range=[0, 100]),
                    hovermode="x unified",
                    template="plotly_white",
                    plot_bgcolor="#fffaf2",
                    paper_bgcolor="#f4efe7",
                    font=dict(family="Palatino, serif", color="#1b1b1f"),
                    showlegend=True,
                )

                chart2_json = json.dumps(chart2, cls=pu.PlotlyJSONEncoder)
            else:
                chart2_json = None

            def compute_correlation_and_trend(x_vals: list[float], y_vals: list[float]):
                count = len(x_vals)
                if count < 2:
                    return None, None, None

                mean_x = sum(x_vals) / count
                mean_y = sum(y_vals) / count

                sxx = sum((x - mean_x) ** 2 for x in x_vals)
                syy = sum((y - mean_y) ** 2 for y in y_vals)
                if sxx == 0 or syy == 0:
                    return None, None, None

                sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_vals, y_vals))
                slope = sxy / sxx
                intercept = mean_y - slope * mean_x
                correlation = sxy / sqrt(sxx * syy)
                return slope, intercept, correlation

            def describe_correlation(correlation: float | None) -> str:
                if correlation is None:
                    return "Correlation: N/A (insufficient variation)"
                magnitude = abs(correlation)
                if magnitude >= 0.7:
                    strength = "Strong"
                elif magnitude >= 0.4:
                    strength = "Moderate"
                elif magnitude >= 0.2:
                    strength = "Weak"
                else:
                    strength = "Very weak"
                direction = "positive" if correlation > 0 else "negative" if correlation < 0 else "neutral"
                return f"Correlation: {strength} {direction} (r={correlation:.2f})"

            if x_values:
                correlation_title = "Win % vs P&L Correlation"
                slope, intercept, correlation = compute_correlation_and_trend(
                    win_pct_values,
                    period_pnl_values,
                )
                chart5_summary = describe_correlation(correlation)
                if correlation is not None:
                    correlation_title = f"Win % vs P&L Correlation (r={correlation:.2f})"

                chart5 = go.Figure()
                chart5.add_trace(go.Scatter(
                    x=win_pct_values,
                    y=period_pnl_values,
                    mode="markers",
                    name="Periods",
                    marker=dict(size=10, color="#f08a24"),
                    customdata=list(zip(x_values, period_trade_counts)),
                    hovertemplate=(
                        "Period: %{customdata[0]}<br>"
                        "Trades: %{customdata[1]}<br>"
                        "Win %: %{x:.2f}%<br>"
                        "PnL: $%{y:.2f}<extra></extra>"
                    ),
                ))

                if slope is not None and intercept is not None:
                    trend_x = [min(win_pct_values), max(win_pct_values)]
                    trend_y = [slope * x + intercept for x in trend_x]
                    chart5.add_trace(go.Scatter(
                        x=trend_x,
                        y=trend_y,
                        mode="lines",
                        name="Trendline",
                        line=dict(color="#4CAF50", width=2),
                    ))

                chart5.update_layout(
                    title=correlation_title,
                    xaxis_title="Win %",
                    yaxis_title="P&L ($)",
                    template="plotly_white",
                    plot_bgcolor="#fffaf2",
                    paper_bgcolor="#f4efe7",
                    font=dict(family="Palatino, serif", color="#1b1b1f"),
                    showlegend=True,
                )

                chart5_json = json.dumps(chart5, cls=pu.PlotlyJSONEncoder)
            else:
                chart5_json = None
                chart5_summary = None

            if x_values:
                trades_title = "# Trades vs P&L Correlation"
                trades_slope, trades_intercept, trades_correlation = compute_correlation_and_trend(
                    [float(v) for v in period_trade_counts],
                    period_pnl_values,
                )
                chart6_summary = describe_correlation(trades_correlation)
                if trades_correlation is not None:
                    trades_title = f"# Trades vs P&L Correlation (r={trades_correlation:.2f})"

                chart6 = go.Figure()
                chart6.add_trace(go.Scatter(
                    x=period_trade_counts,
                    y=period_pnl_values,
                    mode="markers",
                    name="Periods",
                    marker=dict(size=10, color="#2196F3"),
                    customdata=x_values,
                    hovertemplate=(
                        "Period: %{customdata}<br>"
                        "Trades: %{x}<br>"
                        "PnL: $%{y:.2f}<extra></extra>"
                    ),
                ))

                if trades_slope is not None and trades_intercept is not None:
                    trend_x = [min(period_trade_counts), max(period_trade_counts)]
                    trend_y = [trades_slope * x + trades_intercept for x in trend_x]
                    chart6.add_trace(go.Scatter(
                        x=trend_x,
                        y=trend_y,
                        mode="lines",
                        name="Trendline",
                        line=dict(color="#4CAF50", width=2),
                    ))

                chart6.update_layout(
                    title=trades_title,
                    xaxis_title="# Trades",
                    yaxis_title="P&L ($)",
                    template="plotly_white",
                    plot_bgcolor="#fffaf2",
                    paper_bgcolor="#f4efe7",
                    font=dict(family="Palatino, serif", color="#1b1b1f"),
                    showlegend=True,
                )

                chart6_json = json.dumps(chart6, cls=pu.PlotlyJSONEncoder)
            else:
                chart6_json = None
                chart6_summary = None

            ratio_points = [
                (ratio, pnl, label, trades)
                for ratio, pnl, label, trades in zip(
                    period_ratio_values,
                    period_pnl_values,
                    x_values,
                    period_trade_counts,
                )
                if ratio is not None
            ]

            if ratio_points:
                ratio_x = [point[0] for point in ratio_points]
                ratio_y = [point[1] for point in ratio_points]
                ratio_labels = [point[2] for point in ratio_points]
                ratio_trades = [point[3] for point in ratio_points]

                ratio_title = "Avg Winner / Avg Loser vs P&L Correlation"
                ratio_slope, ratio_intercept, ratio_correlation = compute_correlation_and_trend(
                    ratio_x,
                    ratio_y,
                )
                chart7_summary = describe_correlation(ratio_correlation)
                if ratio_correlation is not None:
                    ratio_title = f"Avg Winner / Avg Loser vs P&L Correlation (r={ratio_correlation:.2f})"

                chart7 = go.Figure()
                chart7.add_trace(go.Scatter(
                    x=ratio_x,
                    y=ratio_y,
                    mode="markers",
                    name="Periods",
                    marker=dict(size=10, color="#8E44AD"),
                    customdata=list(zip(ratio_labels, ratio_trades)),
                    hovertemplate=(
                        "Period: %{customdata[0]}<br>"
                        "Trades: %{customdata[1]}<br>"
                        "Win/Loss Avg Ratio: %{x:.2f}<br>"
                        "PnL: $%{y:.2f}<extra></extra>"
                    ),
                ))

                if ratio_slope is not None and ratio_intercept is not None:
                    trend_x = [min(ratio_x), max(ratio_x)]
                    trend_y = [ratio_slope * x + ratio_intercept for x in trend_x]
                    chart7.add_trace(go.Scatter(
                        x=trend_x,
                        y=trend_y,
                        mode="lines",
                        name="Trendline",
                        line=dict(color="#4CAF50", width=2),
                    ))

                chart7.update_layout(
                    title=ratio_title,
                    xaxis_title="Avg Winner / Avg Loser",
                    yaxis_title="P&L ($)",
                    template="plotly_white",
                    plot_bgcolor="#fffaf2",
                    paper_bgcolor="#f4efe7",
                    font=dict(family="Palatino, serif", color="#1b1b1f"),
                    showlegend=True,
                )

                chart7_json = json.dumps(chart7, cls=pu.PlotlyJSONEncoder)
            else:
                chart7_json = None
                chart7_summary = None

            day_source = current_month_daily if view_type == "month" else ytd_daily
            if day_source:
                day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri"]
                day_totals = [0.0] * 5
                day_trade_counts = [0] * 5
                for date_str, values in day_source.items():
                    weekday_idx = date.fromisoformat(date_str).weekday()
                    if weekday_idx > 4:
                        continue
                    day_totals[weekday_idx] += values["pnl"]
                    day_trade_counts[weekday_idx] += values["wins"] + values["losses"]

                if any(day_trade_counts):
                    day_colors = ["#4CAF50" if total >= 0 else "#FF6B6B" for total in day_totals]
                    chart8 = go.Figure()
                    chart8.add_trace(go.Bar(
                        x=day_labels,
                        y=day_totals,
                        marker=dict(color=day_colors),
                        customdata=day_trade_counts,
                        hovertemplate=(
                            "Day: %{x}<br>"
                            "PnL: $%{y:.2f}<br>"
                            "Trades: %{customdata}<extra></extra>"
                        ),
                    ))
                    chart8.update_layout(
                        title="Day of Week vs P&L",
                        xaxis_title="Day of Week",
                        yaxis_title="P&L ($)",
                        template="plotly_white",
                        plot_bgcolor="#fffaf2",
                        paper_bgcolor="#f4efe7",
                        font=dict(family="Palatino, serif", color="#1b1b1f"),
                        showlegend=False,
                    )

                    chart8_json = json.dumps(chart8, cls=pu.PlotlyJSONEncoder)
                else:
                    chart8_json = None
            else:
                chart8_json = None

            if monthly_data:
                sorted_months = sorted(monthly_data.keys())
                month_labels = [date(y, m, 1).strftime("%b %Y") for y, m in sorted_months]
                month_pnls = [monthly_data[k]["pnl"] for k in sorted_months]
                colors = ["#4CAF50" if pnl >= 0 else "#FF6B6B" for pnl in month_pnls]

                chart3 = go.Figure(data=[go.Bar(
                    x=month_labels,
                    y=month_pnls,
                    marker=dict(color=colors),
                    text=[f"${pnl:,.0f}" for pnl in month_pnls],
                    textposition="auto",
                )])
                chart3.update_layout(
                    title="Monthly P&L Comparison",
                    xaxis_title="Month",
                    yaxis_title="P&L ($)",
                    template="plotly_white",
                    plot_bgcolor="#fffaf2",
                    paper_bgcolor="#f4efe7",
                    font=dict(family="Palatino, serif", color="#1b1b1f"),
                    showlegend=False,
                )

                chart3_json = json.dumps(chart3, cls=pu.PlotlyJSONEncoder)
            else:
                chart3_json = None

            if account_id is not None:
                balance_rows = conn.execute(
                    """SELECT date, balance FROM daily_balances
                       WHERE account_id = ?
                       ORDER BY date ASC""",
                    (account_id,),
                ).fetchall()
            else:
                balance_rows = conn.execute(
                    """SELECT date, SUM(balance) as balance FROM daily_balances
                       GROUP BY date
                       ORDER BY date ASC"""
                ).fetchall()

            if balance_rows:
                balance_dates = [row["date"] for row in balance_rows]
                balance_values = [row["balance"] for row in balance_rows]

                chart4 = go.Figure()
                chart4.add_trace(go.Scatter(
                    x=balance_dates,
                    y=balance_values,
                    mode="lines",
                    name="Account Balance",
                    fill="tozeroy",
                    line=dict(color="#2196F3", width=2),
                ))
                chart4.update_layout(
                    title="Account Balance Trend",
                    xaxis_title="Date",
                    yaxis_title="Balance ($)",
                    hovermode="x unified",
                    template="plotly_white",
                    plot_bgcolor="#fffaf2",
                    paper_bgcolor="#f4efe7",
                    font=dict(family="Palatino, serif", color="#1b1b1f"),
                    showlegend=True,
                )

                chart4_json = json.dumps(chart4, cls=pu.PlotlyJSONEncoder)
            else:
                chart4_json = None

        return render_template(
            "analysis.html",
            chart1_json=chart1_json,
            chart2_json=chart2_json,
            chart3_json=chart3_json,
            chart4_json=chart4_json,
            chart5_json=chart5_json,
            chart6_json=chart6_json,
            chart5_summary=chart5_summary,
            chart6_summary=chart6_summary,
            chart7_json=chart7_json,
            chart8_json=chart8_json,
            chart7_summary=chart7_summary,
            chart_preferences=chart_preferences,
            accounts=accounts,
            selected_account=account_id,
            view_type=view_type,
        )

    @app.route("/analysis/preferences", methods=["POST"])
    def save_analysis_preferences():
        payload = request.get_json(silent=True) or {}
        order_raw = payload.get("order")
        visible_raw = payload.get("visible")

        if not isinstance(order_raw, list) or not isinstance(visible_raw, dict):
            return jsonify({"ok": False, "error": "Invalid payload"}), 400

        ordered_ids: list[str] = []
        for item in order_raw:
            if not isinstance(item, str):
                continue
            if item not in ANALYSIS_ALLOWED_CHART_IDS:
                continue
            if item in ordered_ids:
                continue
            ordered_ids.append(item)

        for chart_id in sorted(ANALYSIS_ALLOWED_CHART_IDS):
            if chart_id not in ordered_ids:
                ordered_ids.append(chart_id)

        visible: dict[str, bool] = {}
        for key, value in visible_raw.items():
            if key in ANALYSIS_ALLOWED_CHART_IDS and isinstance(value, bool):
                visible[key] = value

        cleaned_payload = {
            "order": ordered_ids,
            "visible": visible,
        }

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO app_settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (ANALYSIS_PREFS_KEY, json.dumps(cleaned_payload)),
            )

        return jsonify({"ok": True})
