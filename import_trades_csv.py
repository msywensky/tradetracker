from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from tracker.services.import_utils import (
    infer_symbol_from_notes,
    normalize_header,
    parse_datetime,
    parse_int,
    parse_money,
)

DEFAULT_FEE = 0.65

TRADE_REQUIRED_HEADERS = {
    "date",
    "opts traded",
    "avg buy",
    "avg sell",
    "account",
}

BALANCE_REQUIRED_HEADERS = {
    "date",
    "account",
    "balance",
}



def find_header_row(rows: list[list[str]], required_headers: set[str]) -> tuple[int, list[str]] | None:
    for idx, row in enumerate(rows):
        normalized = [normalize_header(cell) for cell in row]
        if required_headers.issubset(set(normalized)):
            return idx, normalized
    return None


def load_nonempty_csv_rows(csv_path: Path) -> list[list[str]]:
    rows: list[list[str]] | None = None
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            with csv_path.open("r", newline="", encoding=encoding) as handle:
                reader = csv.reader(handle)
                rows = [row for row in reader if any(cell.strip() for cell in row)]
            break
        except UnicodeDecodeError:
            continue

    if rows is None:
        raise ValueError(f"Could not decode CSV file {csv_path.name}. Expected UTF-8 or CP1252.")

    return rows


def load_rows_with_headers(csv_path: Path, required_headers: set[str]) -> list[dict[str, str]]:
    rows = load_nonempty_csv_rows(csv_path)

    header_info = find_header_row(rows, required_headers)
    if not header_info:
        raise ValueError(f"Could not find expected header row in {csv_path.name}")

    header_idx, normalized_headers = header_info
    raw_headers = rows[header_idx]
    normalized_map = {normalize_header(h): i for i, h in enumerate(raw_headers)}

    data_rows = []
    for row in rows[header_idx + 1 :]:
        if not any(cell.strip() for cell in row):
            break
        row_dict: dict[str, str] = {}
        for key, col_idx in normalized_map.items():
            if col_idx < len(row):
                row_dict[key] = row[col_idx].strip()
        if row_dict:
            data_rows.append(row_dict)

    return data_rows


def load_trade_rows(csv_path: Path) -> list[dict[str, str]]:
    return load_rows_with_headers(csv_path, TRADE_REQUIRED_HEADERS)


def load_balance_rows(csv_path: Path) -> list[dict[str, str]]:
    return load_rows_with_headers(csv_path, BALANCE_REQUIRED_HEADERS)


def detect_csv_kind(csv_path: Path) -> str:
    rows = load_nonempty_csv_rows(csv_path)

    if find_header_row(rows, TRADE_REQUIRED_HEADERS):
        return "trade"
    if find_header_row(rows, BALANCE_REQUIRED_HEADERS):
        return "balance"

    raise ValueError(
        f"Could not detect CSV type for {csv_path.name}. Expected trade or balance headers."
    )


def ensure_account(conn: sqlite3.Connection, short_name: str) -> int:
    short = short_name.strip().upper()
    existing = conn.execute(
        "SELECT id FROM accounts WHERE short_name = ?",
        (short,),
    ).fetchone()
    if existing:
        return int(existing[0])

    full_name = f"{short} Account"
    conn.execute(
        "INSERT INTO accounts (short_name, full_name, fee_per_contract) VALUES (?, ?, ?)",
        (short, full_name, DEFAULT_FEE),
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def build_trade_code(dt: datetime, counter: int) -> str:
    stamp = dt.strftime("%Y%m%d%H%M%S")
    return f"IMP-{stamp}-{counter:03d}"


def clear_trades_and_entries(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    ensure_schema(conn)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM journal")
    conn.execute("DELETE FROM entries")
    conn.execute("DELETE FROM trades")
    conn.execute("DELETE FROM daily_balances")
    conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('entries', 'trades', 'journal')")
    conn.commit()
    conn.close()


def prompt_clear_tables() -> bool:
    if not sys.stdin.isatty():
        return False

    while True:
        answer = input("Clear existing trades and entries before import? (y/n): ").strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please enter y or n.")


def ensure_schema(conn: sqlite3.Connection) -> None:
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
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_code TEXT UNIQUE NOT NULL,
            symbol TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            closed_at TEXT,
            notes TEXT,
            account_id INTEGER
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            title TEXT,
            text TEXT NOT NULL,
            tags TEXT,
            trade_id INTEGER,
            FOREIGN KEY(trade_id) REFERENCES trades(id)
        )
        """
    )


def convert_csv_price_to_x100(value: float, price_unit: str) -> float:
    if price_unit == "per-share":
        return round(value * 100, 2)
    return round(value, 2)


def convert_opts_traded_to_entry_contracts(
    opts_traded: int,
    contracts_unit: str,
) -> tuple[int, int] | None:
    if contracts_unit == "per-side":
        return opts_traded, opts_traded

    if opts_traded <= 0 or opts_traded % 2 != 0:
        return None

    per_side = opts_traded // 2
    return per_side, per_side


def parse_balance_date(value: str, default_year: int | None) -> str | None:
    raw = value.strip()
    if not raw:
        return None

    year_value = default_year if default_year is not None else datetime.now().year

    if "-" in raw and raw.count("-") == 1:
        try:
            month_text, day_text = raw.split("-", 1)
            month = int(month_text)
            day = int(day_text)
            return datetime(year_value, month, day).date().isoformat()
        except ValueError:
            return None

    if "/" in raw and raw.count("/") == 1:
        try:
            month_text, day_text = raw.split("/", 1)
            month = int(month_text)
            day = int(day_text)
            return datetime(year_value, month, day).date().isoformat()
        except ValueError:
            return None

    for fmt in ("%Y-%m-%d",):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.date().isoformat()
        except ValueError:
            continue

    return None


def import_csv(
    db_path: Path,
    csv_path: Path,
    default_year: int | None,
    price_unit: str,
    contracts_unit: str,
) -> None:
    trade_rows = load_trade_rows(csv_path)

    conn = sqlite3.connect(db_path)
    ensure_schema(conn)
    conn.execute("PRAGMA foreign_keys = ON")

    inserted = 0
    skipped = 0
    weekend_skipped = 0
    invalid_contracts_skipped = 0
    counter = int(conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]) + 1

    for row in trade_rows:
        dt = parse_datetime(row.get("date", ""), default_year)
        if not dt:
            skipped += 1
            continue

        if dt.weekday() >= 5:
            weekend_skipped += 1
            continue

        opts_traded = parse_int(row.get("opts traded", ""))
        avg_buy = parse_money(row.get("avg buy", ""))
        avg_sell = parse_money(row.get("avg sell", ""))
        account_raw = row.get("account", "")
        notes = row.get("notes", "")
        symbol = infer_symbol_from_notes(notes)

        if not opts_traded or avg_buy is None or avg_sell is None:
            skipped += 1
            continue

        entry_contracts = convert_opts_traded_to_entry_contracts(opts_traded, contracts_unit)
        if not entry_contracts:
            invalid_contracts_skipped += 1
            continue
        buy_contracts, sell_contracts = entry_contracts

        account_id = None
        if account_raw:
            account_id = ensure_account(conn, account_raw)

        trade_code = build_trade_code(dt, counter)
        counter += 1

        created_at = dt.strftime("%Y-%m-%d %H:%M:%S")
        closed_at = dt.date().isoformat()

        try:
            conn.execute(
                """
                INSERT INTO trades (trade_code, symbol, status, created_at, closed_at, notes, account_id)
                VALUES (?, ?, 'CLOSED', ?, ?, ?, ?)
                """,
                (trade_code, symbol, created_at, closed_at, notes, account_id),
            )
        except sqlite3.IntegrityError:
            skipped += 1
            continue

        trade_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        buy_price = convert_csv_price_to_x100(avg_buy, price_unit)
        sell_price = convert_csv_price_to_x100(avg_sell, price_unit)

        conn.execute(
            """
            INSERT INTO entries (trade_id, side, contracts, price, created_at)
            VALUES (?, 'BUY', ?, ?, ?)
            """,
            (trade_id, buy_contracts, buy_price, created_at),
        )
        conn.execute(
            """
            INSERT INTO entries (trade_id, side, contracts, price, created_at)
            VALUES (?, 'SELL', ?, ?, ?)
            """,
            (trade_id, sell_contracts, sell_price, created_at),
        )

        inserted += 1

    conn.commit()
    conn.close()

    print(f"Imported trades: {inserted}")
    print(f"Skipped rows: {skipped}")
    print(f"Skipped weekend rows: {weekend_skipped}")
    print(f"Skipped invalid contract rows: {invalid_contracts_skipped}")


def import_balance_csv(db_path: Path, csv_path: Path, default_year: int | None) -> None:
    balance_rows = load_balance_rows(csv_path)

    conn = sqlite3.connect(db_path)
    ensure_schema(conn)

    imported = 0
    skipped = 0

    for row in balance_rows:
        date_raw = row.get("date", "")
        account_raw = row.get("account", "")
        balance_raw = row.get("balance", "")

        if not account_raw:
            skipped += 1
            continue

        balance_date = parse_balance_date(date_raw, default_year)
        balance_value = parse_money(balance_raw)
        if not balance_date or balance_value is None:
            skipped += 1
            continue

        account_id = ensure_account(conn, account_raw)
        conn.execute(
            """
            INSERT OR REPLACE INTO daily_balances (date, account_id, balance)
            VALUES (?, ?, ?)
            """,
            (balance_date, account_id, balance_value),
        )
        imported += 1

    conn.commit()
    conn.close()

    print(f"Imported balances: {imported}")
    print(f"Skipped balance rows: {skipped}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import trade summary CSV into data.db")
    parser.add_argument("csv", nargs="+", help="Path(s) to trade summary CSV export(s)")
    parser.add_argument(
        "--year",
        type=int,
        default=datetime.now().year,
        help="Default year if date has no year (defaults to current year)",
    )
    parser.add_argument(
        "--db",
        default="data.db",
        help="Path to SQLite database file (default: data.db in project root)",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing trades and entries before import",
    )
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Do not clear existing trades and entries before import",
    )
    parser.add_argument(
        "--price-unit",
        choices=["per-contract", "per-share"],
        default="per-contract",
        help=(
            "How CSV Avg Buy/Avg Sell values are expressed: "
            "per-contract (default) or per-share"
        ),
    )
    parser.add_argument(
        "--contracts-unit",
        choices=["round-trip-total", "per-side"],
        default="round-trip-total",
        help=(
            "How Opts Traded is expressed: round-trip-total (default, split equally between "
            "BUY/SELL) or per-side"
        ),
    )
    args = parser.parse_args()

    if args.clear and args.no_clear:
        parser.error("Use only one of --clear or --no-clear")

    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = Path(__file__).resolve().parent / db_path

    csv_paths = [Path(csv_file) for csv_file in args.csv]
    csv_kinds: dict[Path, str] = {}
    for csv_path in csv_paths:
        csv_kinds[csv_path] = detect_csv_kind(csv_path)

    has_trade_csv = any(kind == "trade" for kind in csv_kinds.values())

    should_clear = args.clear or (not args.no_clear and has_trade_csv and prompt_clear_tables())
    if should_clear:
        clear_trades_and_entries(db_path)
        print("Cleared entries and trades.")

    for csv_path in csv_paths:
        csv_kind = csv_kinds[csv_path]
        if csv_kind == "trade":
            import_csv(db_path, csv_path, args.year, args.price_unit, args.contracts_unit)
        else:
            import_balance_csv(db_path, csv_path, args.year)


if __name__ == "__main__":
    main()
