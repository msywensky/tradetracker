# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```powershell
# Run the app
python app.py

# Run all tests
pytest -q

# Run a single test file
pytest tests/test_routes.py -q

# Run a single test class or method
pytest tests/test_routes.py::RouteIntegrationTests::test_name -q

# Bulk-import trades from CSV
python import_trades_csv.py <file.csv> [--no-clear] [--year 2026]
```

## Architecture

Flask 3 + SQLite app with no ORM and no Blueprints. Manual dependency injection via function arguments.

- **`app.py`** — app factory, `get_db()` context manager, `init_db()` (handles schema migrations inline), template filters (`money`, `pct`), and `register_all_routes()` call
- **`tracker/routes/`** — one file per feature area (`home`, `trades`, `accounts`, `journal`, `reports`); each exports `register_*_routes(app, get_db, ...)` and receives all dependencies as arguments
- **`tracker/services/stats.py`** — `compute_trade_stats(entries, fee_per_contract)` is a pure function; takes any iterable of mappings, returns a dict of PnL/contract stats
- **`tracker/services/import_utils.py`** — CSV parsing helpers used by `import_trades_csv.py`
- **`templates/`** — all extend `layout.html`; Plotly charts rendered server-side via `json.dumps(..., cls=PlotlyJSONEncoder)` and initialized client-side

## Database

`get_db()` is a `@contextmanager` that auto-commits on success, rolls back on exception, and always closes. Always use it as `with get_db() as conn:`. Never call `conn.commit()` inside the block.

Tables: `accounts`, `trades`, `entries`, `journal`, `daily_balances`, `app_settings`.

Trade PnL is stored at the entry level (BUY/SELL rows in `entries`); `compute_trade_stats` aggregates on the fly. Prices in `entries.price` are per-contract (not per-share).

Always use `?` placeholders — never f-strings or string concatenation in SQL.

## Route Pattern

Route modules never import `get_db`, `app`, or other app-level objects directly. All dependencies are passed in:

```python
def register_trade_routes(app, get_db, fetch_entries, compute_trade_stats, now_iso_date, now_iso_dt, generate_trade_code):
    @app.route("/trade/create", methods=["POST"])
    def create_trade():
        ...
```

## CSRF

All HTML POST forms must include `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`.  
JSON fetch POSTs must send `X-CSRFToken` header read from `<meta name="csrf-token">`.

## Testing

Each test class creates an isolated `tempfile` SQLite DB, patches `trade_app.DB_PATH`, disables CSRF (`WTF_CSRF_ENABLED = False`), calls `trade_app.init_db()`, then creates `trade_app.app.test_client()`. Insert fixture rows directly via `sqlite3.connect(self.db_path)` — not through `get_db()`.

## Constraints

- No ORM — raw `sqlite3` is intentional
- No Flask Blueprints — the `register_*_routes` pattern is intentional
- No `| safe` on user-controlled data in templates — use `| tojson` instead
