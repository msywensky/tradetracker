from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data.db"

def is_weekend(date_str: str) -> bool:
    # Supports YYYY-MM-DD or YYYY-MM-DD HH:MM:SS
    date_part = date_str.split(" ")[0]
    day = datetime.strptime(date_part, "%Y-%m-%d").date()
    return day.weekday() >= 5

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

trade_rows = cur.execute("SELECT id, closed_at FROM trades WHERE closed_at IS NOT NULL").fetchall()
weekend_trade_ids = [trade_id for trade_id, closed_at in trade_rows if is_weekend(closed_at)]

entries_removed = 0
trades_removed = 0
balances_removed = 0

if weekend_trade_ids:
    placeholders = ",".join(["?"] * len(weekend_trade_ids))
    entries_removed = cur.execute(
        f"DELETE FROM entries WHERE trade_id IN ({placeholders})",
        weekend_trade_ids,
    ).rowcount
    trades_removed = cur.execute(
        f"DELETE FROM trades WHERE id IN ({placeholders})",
        weekend_trade_ids,
    ).rowcount

balance_rows = cur.execute("SELECT date FROM daily_balances").fetchall()
weekend_balance_dates = [date_str for (date_str,) in balance_rows if is_weekend(date_str)]

if weekend_balance_dates:
    placeholders = ",".join(["?"] * len(weekend_balance_dates))
    balances_removed = cur.execute(
        f"DELETE FROM daily_balances WHERE date IN ({placeholders})",
        weekend_balance_dates,
    ).rowcount

conn.commit()
conn.close()

print(f"Weekend trades removed: {trades_removed}")
print(f"Weekend entries removed: {entries_removed}")
print(f"Weekend balances removed: {balances_removed}")
