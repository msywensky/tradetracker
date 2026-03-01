from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from pathlib import Path
import random

from flask import Flask
from flask_wtf.csrf import CSRFProtect

from tracker.routes import register_all_routes
from tracker.services.stats import compute_trade_stats

APP_ROOT = Path(__file__).parent
DB_PATH = APP_ROOT / "data.db"

app = Flask(__name__)
app.secret_key = os.environ.get("TRADETRACKER_SECRET_KEY", "dev-secret-key")
csrf = CSRFProtect(app)


def next_weekday(value: date) -> date:
    if value.weekday() >= 4:
        days_ahead = 7 - value.weekday()
    else:
        days_ahead = 1
    return value + timedelta(days=days_ahead)


@app.context_processor
def inject_globals():
    today = date.today()
    return {
        "today": today,
        "next_expiration": next_weekday(today),
        "date": date,
        "timedelta": timedelta,
    }


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                short_name TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                fee_per_contract REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_code TEXT UNIQUE NOT NULL,
                symbol TEXT NOT NULL,
                option_type TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                closed_at TEXT,
                notes TEXT,
                account_id INTEGER,
                expiration TEXT,
                strike REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL,
                side TEXT NOT NULL,
                contracts INTEGER NOT NULL,
                price REAL NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(trade_id) REFERENCES trades(id)
            )
            """
        )

        # Journal table for journaling feature
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                text TEXT NOT NULL,
                tags TEXT,
                trade_id INTEGER,
                FOREIGN KEY(trade_id) REFERENCES trades(id)
            )
            """
        )

        journal_columns = {row["name"] for row in conn.execute("PRAGMA table_info(journal)")}
        if "title" not in journal_columns:
            conn.execute("ALTER TABLE journal ADD COLUMN title TEXT")

        # Migrate entries.price from INTEGER to REAL if needed
        entries_cols = {row["name"]: row["type"] for row in conn.execute("PRAGMA table_info(entries)")}
        if entries_cols.get("price", "").upper() == "INTEGER":
            conn.execute("ALTER TABLE entries RENAME TO entries_old")
            conn.execute(
                """
                CREATE TABLE entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id INTEGER NOT NULL,
                    side TEXT NOT NULL,
                    contracts INTEGER NOT NULL,
                    price REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(trade_id) REFERENCES trades(id)
                )
                """
            )
            conn.execute("INSERT INTO entries SELECT * FROM entries_old")
            conn.execute("DROP TABLE entries_old")

        trade_columns = {row["name"] for row in conn.execute("PRAGMA table_info(trades)")}
        if "account_id" not in trade_columns:
            conn.execute("ALTER TABLE trades ADD COLUMN account_id INTEGER")
        if "option_type" not in trade_columns:
            conn.execute("ALTER TABLE trades ADD COLUMN option_type TEXT")
        if "expiration" not in trade_columns:
            conn.execute("ALTER TABLE trades ADD COLUMN expiration TEXT")
        if "strike" not in trade_columns:
            conn.execute("ALTER TABLE trades ADD COLUMN strike REAL")

        balance_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='daily_balances'"
        ).fetchone()
        if balance_exists:
            balance_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(daily_balances)")
            }
            if "account_id" not in balance_columns:
                conn.execute("ALTER TABLE daily_balances RENAME TO daily_balances_old")
                conn.execute(
                    """
                    CREATE TABLE daily_balances (
                        date TEXT NOT NULL,
                        account_id INTEGER,
                        balance REAL NOT NULL,
                        PRIMARY KEY (date, account_id)
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO daily_balances (date, account_id, balance)
                    SELECT date, NULL, balance FROM daily_balances_old
                    """
                )
                conn.execute("DROP TABLE daily_balances_old")
        else:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_balances (
                    date TEXT NOT NULL,
                    account_id INTEGER,
                    balance REAL NOT NULL,
                    PRIMARY KEY (date, account_id)
                )
                """
            )


def now_iso_date() -> str:
    return date.today().isoformat()


def now_iso_dt() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def generate_sample_data() -> None:
    """Generate sample trading data for January and February 2026"""
    with get_db() as conn:
        existing_trades = conn.execute("SELECT COUNT(*) as cnt FROM trades").fetchone()["cnt"]
        if existing_trades > 0:
            return

        cur = conn.cursor()

        cur.execute(
            "INSERT OR IGNORE INTO accounts (short_name, full_name, fee_per_contract) VALUES (?, ?, ?)",
            ("INV", "Investment Account", 0.65),
        )
        cur.execute(
            "INSERT OR IGNORE INTO accounts (short_name, full_name, fee_per_contract) VALUES (?, ?, ?)",
            ("IRA", "IRA Account", 0.65),
        )

        accounts = cur.execute(
            "SELECT id, short_name FROM accounts WHERE short_name IN ('INV', 'IRA')"
        ).fetchall()
        account_map = {acc["short_name"]: acc["id"] for acc in accounts}

        symbols = ["SPY", "QQQ", "IWM", "XLF", "XLE"]

        jan_dates = [date(2026, 1, d) for d in range(5, 30, 2)]
        feb_dates = [date(2026, 2, d) for d in range(2, 13)]

        trade_counter = 1

        for trade_date in jan_dates + feb_dates:
            symbol = random.choice(symbols)
            account_name = random.choice(["INV", "IRA"])
            account_id = account_map[account_name]

            is_winning = random.random() < 0.7

            trade_code = f"{symbol}-{trade_counter:02d}"
            trade_counter += 1

            buy_price = int(random.randint(200, 500) * 100)
            contracts = random.randint(1, 5)

            if is_winning:
                spread = random.randint(25, 150)
                sell_price = buy_price + spread
            else:
                loss = random.randint(25, 150)
                sell_price = buy_price - loss

            cur.execute(
                """INSERT INTO trades (trade_code, symbol, status, created_at, closed_at, account_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    trade_code,
                    symbol,
                    "CLOSED",
                    trade_date.isoformat(),
                    trade_date.isoformat(),
                    account_id,
                ),
            )
            trade_id = cur.lastrowid

            cur.execute(
                """INSERT INTO entries (trade_id, side, contracts, price, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (trade_id, "BUY", contracts, buy_price, trade_date.isoformat()),
            )

            cur.execute(
                """INSERT INTO entries (trade_id, side, contracts, price, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (trade_id, "SELL", contracts, sell_price, trade_date.isoformat()),
            )

        inv_balance = 1000000
        ira_balance = 20000

        cur.execute(
            "INSERT OR IGNORE INTO daily_balances (date, account_id, balance) VALUES (?, ?, ?)",
            ("2026-01-01", account_map["INV"], inv_balance),
        )
        cur.execute(
            "INSERT OR IGNORE INTO daily_balances (date, account_id, balance) VALUES (?, ?, ?)",
            ("2026-01-01", account_map["IRA"], ira_balance),
        )

        for trade_date in jan_dates + feb_dates:
            inv_balance += random.randint(-5000, 15000)
            ira_balance += random.randint(-200, 800)

            cur.execute(
                "INSERT OR IGNORE INTO daily_balances (date, account_id, balance) VALUES (?, ?, ?)",
                (trade_date.isoformat(), account_map["INV"], max(500000, inv_balance)),
            )
            cur.execute(
                "INSERT OR IGNORE INTO daily_balances (date, account_id, balance) VALUES (?, ?, ?)",
                (trade_date.isoformat(), account_map["IRA"], max(10000, ira_balance)),
            )

        conn.commit()


def should_generate_sample_data() -> bool:
    with get_db() as conn:
        existing_trades = conn.execute("SELECT COUNT(*) as cnt FROM trades").fetchone()["cnt"]

    if existing_trades > 0:
        return False

    try:
        response = input("No trades found. Generate sample data now? [y/N]: ").strip().lower()
    except EOFError:
        return False

    return response in {"y", "yes"}


def generate_trade_code() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = random.randint(1000, 9999)
    return f"TRD-{stamp}-{suffix}"


def fetch_entries(conn: sqlite3.Connection, trade_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM entries WHERE trade_id = ? ORDER BY id", (trade_id,)
    ).fetchall()


register_all_routes(
    app,
    get_db,
    fetch_entries,
    compute_trade_stats,
    now_iso_date,
    now_iso_dt,
    generate_trade_code,
)


@app.template_filter("money")
def money(value: float | int | None) -> str:
    if value is None:
        return "$0.00"
    return f"${value:,.2f}"


@app.template_filter("pct")
def pct(value: float | int) -> str:
    return f"{value:,.2f}%"


if __name__ == "__main__":
    init_db()
    if should_generate_sample_data():
        generate_sample_data()
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(debug=debug)
