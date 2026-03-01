# CSV Import Guide

`import_trades_csv.py` is a command-line tool that bulk-imports options trade data and daily account balances into the tracker's SQLite database (`data.db`).

---

## Usage

```powershell
python import_trades_csv.py <file(s)> [options]
```

The script auto-detects whether each file is a **trade CSV** or a **balance CSV** by inspecting its headers. You can pass multiple files of either type in one command.

---

## Examples

| Goal | Command |
|---|---|
| Import a single month of trades | `python import_trades_csv.py jan.csv` |
| Import two months, keep existing data | `python import_trades_csv.py jan.csv feb.csv --no-clear` |
| Import balances only | `python import_trades_csv.py balances.csv --no-clear` |
| Import trades + balances together | `python import_trades_csv.py jan.csv balances.csv --no-clear` |
| Import with a specific year for yearless dates | `python import_trades_csv.py jan.csv --year 2026` |
| Import into a different database | `python import_trades_csv.py jan.csv --db archive.db` |

---

## CLI Options

| Option | Default | Description |
|---|---|---|
| `csv` (positional) | — | One or more CSV file paths |
| `--year <YYYY>` | Current year | Default year injected when CSV dates have no year component (e.g. `1/15 9:30 AM`) |
| `--db <path>` | `data.db` | Path to the SQLite file; relative paths are resolved from the project root |
| `--clear` | false | Clear all trades, entries, journal entries, and daily balances before import |
| `--no-clear` | false | Skip clearing and skip the interactive prompt |
| `--price-unit` | `per-contract` | How Avg Buy / Avg Sell values are expressed — `per-contract` or `per-share` |
| `--contracts-unit` | `round-trip-total` | How `Opts Traded` is expressed — `round-trip-total` (split equally between BUY/SELL legs) or `per-side` |

> `--clear` and `--no-clear` are mutually exclusive.  
> When importing a trade CSV without either flag, the script will interactively prompt whether to clear existing data.

---

## Trade CSV Format

The script scans for a header row containing at minimum these columns (case-insensitive, extra whitespace ignored):

| Required column | Example value |
|---|---|
| `Date` | `1/15/2026 09:30 AM` or `1/15 9:30 AM` |
| `Opts Traded` | `10` |
| `Avg Buy` | `$2.35` or `2.35` |
| `Avg Sell` | `$2.80` |
| `Account` | `IRA` |

**Optional columns** (used when present):

| Column | Notes |
|---|---|
| `Notes` / `Description` | Free text; the symbol is inferred from it using pattern matching (SPY, TSLA, MSFT, NBIS) |
| Any extra columns | Silently ignored |

### How entries are created

For each trade row the importer creates **two entries** in the database:

- A `BUY` entry — `contracts` based on `Opts Traded` (or half of it if `round-trip-total`), `price` = Avg Buy
- A `SELL` entry — same contracts, `price` = Avg Sell

If only one side has a non-zero price, only that entry is created.

### Price unit

| `--price-unit` | Behaviour |
|---|---|
| `per-contract` (default) | Avg Buy / Avg Sell are stored as-is (options are priced per contract in the app) |
| `per-share` | Values are multiplied by 100 to convert to per-contract |

### Contracts unit

| `--contracts-unit` | Behaviour |
|---|---|
| `round-trip-total` (default) | `Opts Traded` is the total round-trip count; each leg gets `Opts Traded / 2` contracts |
| `per-side` | `Opts Traded` is already the per-leg count |

### Account auto-creation

If an account referenced in the CSV does not exist in the database, it is created automatically with:
- `short_name` = uppercased value from the `Account` column
- `full_name` = same
- `fee_per_contract` = `0.65` (default)

---

## Balance CSV Format

The script recognises a balance file when it finds a header row with:

| Required column | Example value |
|---|---|
| `date` | `2026-01-31` |
| `account` | `IRA` |
| `balance` | `$12,500.00` or `12500` |

Rows are upserted into `daily_balances` with `(date, account_id)` as the composite primary key — re-importing the same file is safe.

---

## Date Formats Supported

The importer tries the following formats in order:

| Format | Example |
|---|---|
| `YYYY-MM-DD HH:MM` | `2026-01-15 09:30` |
| `YYYY-MM-DD HH:MM:SS` | `2026-01-15 09:30:00` |
| `MM/DD/YYYY HH:MM AM/PM` | `01/15/2026 9:30 AM` |
| `MM/DD HH:MM AM/PM` *(requires `--year`)* | `1/15 9:30 AM` |
| `MM/DD/YYYY` | `01/15/2026` |
| `MM/DD` *(requires `--year`)* | `1/15` |

---

## Clearing Existing Data

`--clear` deletes all rows from:
- `trades`
- `entries`
- `journal`
- `daily_balances`

And resets the SQLite autoincrement sequences for those tables. Use this when re-importing a full history to avoid duplicate records.

---

## File Encoding

The script tries `utf-8-sig` first (standard Excel UTF-8 export), then falls back to `cp1252` (Windows Western). Files that cannot be read with either encoding will raise an error.
