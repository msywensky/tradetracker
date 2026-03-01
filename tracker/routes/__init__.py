from __future__ import annotations

from .accounts import register_account_routes
from .home import register_home_routes
from .reports import register_report_routes
from .trades import register_trade_routes
from .journal import register_journal_routes


def register_all_routes(
    app,
    get_db,
    fetch_entries,
    compute_trade_stats,
    now_iso_date,
    now_iso_dt,
    generate_trade_code,
) -> None:
    register_home_routes(app, get_db)
    register_account_routes(app, get_db)
    register_trade_routes(
        app,
        get_db,
        fetch_entries,
        compute_trade_stats,
        now_iso_date,
        now_iso_dt,
        generate_trade_code,
    )
    register_report_routes(app, get_db, fetch_entries, compute_trade_stats)
    register_journal_routes(app, get_db)
