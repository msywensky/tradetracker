# Options Trade Tracker

Flask + SQLite app for tracking options trades, account balances, performance, and a trading journal.

## Features

- **Trades** — create trades with BUY/SELL entry legs, notes, expiration, and strike; auto-generated trade codes
- **Accounts** — create, edit, and delete brokerage accounts; set a default; per-account fee tracking
- **Balances** — log daily account balances directly from the home page
- **Monthly view** — calendar layout with daily P&L summaries and editable daily balances
- **YTD view** — year-to-date summary with monthly breakdown
- **Analysis** — interactive Plotly performance charts; chart layout preferences persisted per session
- **Journal** — date-stamped trading journal with optional title, tags, and trade linking
- **CSV import** — bulk-import trade entries and balance history from CSV files (see [CSV_IMPORT.md](CSV_IMPORT.md))

## Quick Start (Windows)

1. Create and activate a virtual environment:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
2. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
3. Run the app:
   ```powershell
   python app.py
   ```
4. Open `http://127.0.0.1:5000/` in your browser.

> The database (`data.db`) is created automatically on first run. Sample data is seeded if the database is empty.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `TRADETRACKER_SECRET_KEY` | `dev-secret-key` | Flask session signing key — **change this in production** |
| `FLASK_DEBUG` | `1` | Set to `0` to disable the Werkzeug debugger in production |

## Pages

| Page | URL | Description |
|---|---|---|
| Trades | `/` | Open trades, today's closes, recent balances, quick balance entry |
| Accounts | `/accounts` | Account list — add, edit, delete, set default |
| Trade detail | `/trade/<id>` | Entry log, stats (P&L, fees, % return), close/delete |
| Monthly | `/month/<year>/<month>` | Calendar view, daily P&L, editable balances |
| YTD | `/ytd/<year>` | Year-to-date stats by month |
| Analysis | `/analysis` | Interactive Plotly charts |
| Journal | `/journal` | Add journal entries, view past entries, link to closed trades |

## Security

- **CSRF protection** — all state-changing POST forms include a CSRF token via `flask-wtf`. The journal's `fetch` POST sends an `X-CSRFToken` header. Tests disable CSRF with `WTF_CSRF_ENABLED = False`.
- **Debug mode** — controlled by `FLASK_DEBUG` env var (default `1` / enabled). Set to `0` before exposing the app on a network.
- **Secret key** — set `TRADETRACKER_SECRET_KEY` in the environment; the hardcoded fallback is for local development only.

## Testing

```powershell
pytest -q
```

62 tests, 85 % coverage. The suite covers:

- Route integration (home, accounts, trades, reports, balance)
- Journal API (add/fetch/filter, validation error paths, trade linking)
- Analysis chart payloads (`chart1`–`chart4`)
- Trade statistics (`compute_trade_stats` — P&L, fees, percent for debit/credit strategies)
- CSV import utilities and CLI importer

## CSV Import

See **[CSV_IMPORT.md](CSV_IMPORT.md)** for full usage, options, and column reference.

## Architecture

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for module layout, DB schema, route table, and data flow.

## CI

GitHub Actions workflow runs `pytest -q` on every push and pull request to `main`.  
Config: `.github/workflows/ci.yml`

## Data

SQLite database file: `data.db` (project root, git-ignored).
