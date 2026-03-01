# Options Trade Tracker — Architecture

---

## 1. Overview

| Item | Detail |
|---|---|
| **Language** | Python 3.13 |
| **Web framework** | Flask (no Blueprints — manual route registration) |
| **Database** | SQLite via `sqlite3` (row_factory = `sqlite3.Row`) |
| **Charting** | Plotly (server-side JSON, rendered client-side) |
| **Styling** | Vanilla CSS (`static/styles.css`), Font Awesome icons |
| **CSRF protection** | flask-wtf `CSRFProtect` — tokens in all POST forms; `X-CSRFToken` header for JSON fetch |
| **Testing** | pytest + pytest-cov (85 % coverage, 62 tests) |
| **Entry point** | `app.py` → `python app.py` |

---

## 2. Project Layout

```
tradetracker/
├── app.py                      # App factory, DB init, filters, route wiring
├── import_trades_csv.py        # CLI: import trades & balances from CSV
├── check_db.py                 # CLI: quick DB stats / sanity check
├── remove_weekend_data.py      # CLI: strip weekend balance rows
├── requirements.txt
├── data.db                     # SQLite database (git-ignored)
│
├── tracker/
│   ├── routes/
│   │   ├── __init__.py         # register_all_routes()
│   │   ├── home.py             # / and /journal page routes
│   │   ├── accounts.py         # /accounts CRUD
│   │   ├── trades.py           # /trade/* CRUD
│   │   ├── reports.py          # /month, /ytd, /analysis, /update_balance
│   │   └── journal.py          # /journal/* JSON API
│   └── services/
│       ├── stats.py            # compute_trade_stats()
│       └── import_utils.py     # CSV parsing helpers
│
├── templates/
│   ├── layout.html             # Base template (nav, theme toggle)
│   ├── index.html              # Home — open trades, today's closes, balances
│   ├── trade.html              # Trade detail + inline entry management
│   ├── accounts.html           # Account list + inline add/edit/delete
│   ├── month.html              # Monthly calendar + summary
│   ├── ytd.html                # Year-to-date summary
│   ├── analysis.html           # Performance charts (Plotly)
│   └── journal.html            # Journal form + past-entries list
│
├── static/
│   └── styles.css
│
└── tests/
    ├── test_routes.py
    ├── test_journal.py
    ├── test_analysis.py
    ├── test_stats.py
    ├── test_import_trades_csv.py
    └── test_import_utils.py
```

---

## 3. Application Bootstrap (`app.py`)

### Initialisation sequence
1. `DB_PATH` resolved from `APP_ROOT / "data.db"`
2. `app.secret_key` from env var `TRADETRACKER_SECRET_KEY` (falls back to `"dev-secret-key"`)
3. `CSRFProtect(app)` enables CSRF validation on all POST requests
4. `init_db()` creates/migrates all tables (see §4)
5. `register_all_routes(app, get_db, ...)` wires every route module
6. `generate_sample_data()` seeds data if DB is empty

**Debug mode**: controlled by `FLASK_DEBUG` env var (default `"1"` = enabled). Set to `0` in production.

### Key helpers

| Helper | Purpose |
|---|---|
| `get_db()` | `@contextmanager` — opens a `sqlite3.Row` connection, wraps it in `with conn:` (auto-commit/rollback), closes in `finally` |
| `fetch_entries(conn, trade_id)` | Returns all entries for a trade as a list of dicts |
| `generate_trade_code()` | Produces `TRD-YYYYMMDDHHMMSS-<4-digit-random>` |
| `now_iso_date()` | `date.today().isoformat()` |
| `now_iso_dt()` | `datetime.now()` as `YYYY-MM-DD HH:MM:SS` |
| `next_weekday(d)` | Next Mon–Fri from a given date |

### Jinja2 template filters

| Filter | Behaviour |
|---|---|
| `money` | Formats a float as `$1,234.56`; returns `$0.00` for `None` |
| `percent` | Formats a float as `12.3%` |

### Context processor (`inject_globals`)
Injects into every template: `today`, `next_expiration`, `date`, `timedelta`.

---

## 4. Database Schema

### `accounts`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | autoincrement |
| short_name | TEXT UNIQUE | e.g. `IRA` |
| full_name | TEXT | e.g. `Fidelity IRA` |
| fee_per_contract | REAL | e.g. `0.65` |

### `trades`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| trade_code | TEXT UNIQUE | `TRD-YYYYMMDDHHMMSS-NNNN` |
| symbol | TEXT | e.g. `SPY` |
| option_type | TEXT | `CALL` \| `PUT` |
| status | TEXT | `OPEN` \| `CLOSED` |
| created_at | TEXT | ISO datetime |
| closed_at | TEXT | ISO date, nullable |
| notes | TEXT | |
| account_id | INTEGER FK → accounts | nullable |
| expiration | TEXT | ISO date, nullable |
| strike | REAL | nullable |

### `entries`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| trade_id | INTEGER FK → trades | |
| side | TEXT | `BUY` \| `SELL` |
| contracts | INTEGER | |
| price | **REAL** | option premium per contract |
| created_at | TEXT | ISO datetime |

### `daily_balances`
| Column | Type | Notes |
|---|---|---|
| date | TEXT | ISO date — composite PK |
| account_id | INTEGER FK → accounts | composite PK, nullable |
| balance | REAL | |

### `app_settings`
| Column | Type | Notes |
|---|---|---|
| key | TEXT PK | e.g. `default_account_id`, `analysis_chart_preferences` |
| value | TEXT | JSON or plain string |

### `journal`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| date | TEXT | ISO date |
| title | TEXT | optional, added via ALTER TABLE migration |
| text | TEXT NOT NULL | free-form notes |
| tags | TEXT | comma-separated |
| trade_id | INTEGER FK → trades | optional link |

### Schema migrations (run inside `init_db()`)
- `entries.price INTEGER → REAL` — rename/recreate/copy pattern
- `journal.title` — `ALTER TABLE … ADD COLUMN` if absent
- `trades.account_id / option_type / expiration / strike` — `ADD COLUMN` if absent
- `daily_balances.account_id` — rename/recreate/copy pattern

---

## 5. Route Modules

### Route registration pattern
Each module exposes `register_*_routes(app, get_db, ...)`. All modules are wired in `tracker/routes/__init__.py → register_all_routes()`. No Flask Blueprints are used.

### `home.py` — `register_home_routes(app, get_db)`
| Endpoint | Method | URL | Description |
|---|---|---|---|
| `index` | GET | `/` | Open trades, today's closes, recent balances, account selector |
| `journal_page` | GET | `/journal` | Journal form + past entries + today's closed trades dropdown |

Account selection: reads `session["selected_account_id"]` → falls back to `default_account_id` from `app_settings`.

### `accounts.py` — `register_account_routes(app, get_db)`
| Endpoint | Method | URL |
|---|---|---|
| `accounts_page` | GET | `/accounts` |
| `create_account` | POST | `/account/create` |
| `update_account` | POST | `/account/<id>/update` |
| `delete_account` | POST | `/account/<id>/delete` |
| `set_default_account` | POST | `/account/<id>/set_default` |

`delete_account` guards: blocks if trades exist; cascades `daily_balances` deletion.

### `trades.py` — `register_trade_routes(app, get_db, fetch_entries, compute_trade_stats, now_iso_date, now_iso_dt, generate_trade_code)`
| Endpoint | Method | URL |
|---|---|---|
| `create_trade` | POST | `/trade/create` |
| `trade_detail` | GET | `/trade/<id>` |
| `add_entry` | POST | `/trade/<id>/add_entry` |
| `update_entry` | POST | `/entry/<id>/update` |
| `delete_entry` | POST | `/entry/<id>/delete` |
| `close_trade` | POST | `/trade/<id>/close` |
| `delete_trade` | POST | `/trade/<id>/delete` |

`close_trade` guards against re-closing. `delete_trade` cascades journal and entries deletion.

### `reports.py` — `register_report_routes(app, get_db, fetch_entries, compute_trade_stats)`
| Endpoint | Method | URL |
|---|---|---|
| `month_summary` | GET | `/month/<year>/<month>` |
| `ytd_summary` | GET | `/ytd/<year>` |
| `analysis` | GET | `/analysis` |
| `update_balance` | POST | `/update_balance` |
| `save_analysis_preferences` | POST | `/analysis/preferences` |

Account filtering: `resolve_selected_account_id()` checks query arg → session → default. Analysis chart preferences stored as JSON in `app_settings`.

### `journal.py` — `register_journal_routes(app, get_db)`
All endpoints return JSON.

| Endpoint | Method | URL |
|---|---|---|
| `journal_get_entries` | GET | `/journal/entries` |
| `journal_get_entries_for_date` | GET | `/journal/entries/<date>` |
| `journal_add_entry` | POST | `/journal/entry` |
| `journal_closed_trades_today` | GET | `/journal/closed_trades_today` |

`journal_add_entry` validates: date format (`YYYY-MM-DD`), non-empty text. Returns HTTP 400 on validation failure.

---

## 6. Services

### `tracker/services/stats.py` — `compute_trade_stats(entries, fee_per_contract)`

Returns a dict with:
- `buy_contracts`, `sell_contracts`, `total_contracts`
- `avg_buy`, `avg_sell`
- `pnl_before` — gross P&L (sell_total − buy_total)
- `fees` — `total_contracts × fee_per_contract`
- `pnl_after` — net P&L after fees
- `percent` — `pnl_before / max(buy_total, sell_total) × 100` (handles both credit and debit strategies)

### `tracker/services/import_utils.py`

| Function | Purpose |
|---|---|
| `normalize_header(s)` | Lowercase + collapse whitespace |
| `parse_money(s)` | Strips `$`, commas, parenthesised negatives → `float` |
| `parse_int(s)` | Strips commas → `int` |
| `parse_datetime(s, year)` | Tries multiple date/datetime formats; injects year for yearless formats |
| `infer_symbol(s)` | Regex match against `SYMBOL_PATTERN` (SPY, TSLA, MSFT, NBIS) |

---

## 7. CLI Tools

### `import_trades_csv.py`
Imports trade entries and daily balances from a CSV file.

Key functions:
- `ensure_schema(conn)` — mirrors `init_db()` schema (all tables including journal)
- `build_trade_code(row, dt)` — `TRD-YYYYMMDDHHMMSS-<random>` from CSV row date
- `clear_trades_and_entries(conn)` — drops all trades, entries, journal entries, resets sequences
- `main()` — CLI: `python import_trades_csv.py <file.csv> [--account SHORT_NAME]`

### `check_db.py`
Prints table row counts and lists recent trades. Ad-hoc diagnostic.

### `remove_weekend_data.py`
Deletes `daily_balances` rows where `strftime('%w', date)` is `0` (Sun) or `6` (Sat).

---

## 8. Frontend

### Templates
All templates extend `layout.html`. Jinja2 template filters (`money`, `percent`) are used throughout.

| Template | Key data passed from route |
|---|---|
| `index.html` | `open_trades`, `closed_trades`, `recent_balances`, `accounts`, `selected_account_id` |
| `trade.html` | `trade`, `entries`, `stats`, `accounts` |
| `accounts.html` | `accounts`, `default_account_id`, `account_error` |
| `month.html` | `month_start`, `trades`, `balances`, `stats_by_day`, `accounts` |
| `ytd.html` | `year`, `months`, `annual_stats`, `accounts` |
| `analysis.html` | `charts` (Plotly JSON), `preferences`, `accounts` |
| `journal.html` | `today`, `month_start`, `closed_trades_today`, `journal_entries` |

### Accounts page (list layout)
Accounts are rendered as a `<ul class="account-list">`. Each row shows short name, star badge if default, full name, fee, and inline Edit / Set Default / Delete buttons. Clicking **Edit** expands an inline form beneath the row.

### CSRF
`layout.html` injects `<meta name="csrf-token" content="{{ csrf_token() }}">` into every page. All HTML POST forms include `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`. The journal's JavaScript `fetch` POST reads the meta tag and sends it as the `X-CSRFToken` request header. flask-wtf validates the token server-side on every non-GET request.

### Journal page
- Form grid: date, title (optional), notes textarea, tags (comma-separated), linked trade dropdown (today's closed trades only)
- Tag chip preview uses DOM methods (not `innerHTML`) to prevent XSS
- Past entries rendered as cards with linked trade context

### `month.html` calendar
`days_in_month` computed via date arithmetic (`next_month_start − month_start`).days to correctly handle all month lengths.

### JavaScript
Vanilla JS; no framework. Inline `<script>` blocks per template handle:
- Account inline edit toggle
- Journal form submission (fetch POST → reload)
- Tag chip preview
- Theme toggle (localStorage `"dark"` / `""`)
- Plotly chart rendering from embedded JSON

---

## 9. Testing

| File | Coverage focus |
|---|---|
| `test_routes.py` | Route integration: render, account CRUD, trade CRUD, balance update |
| `test_journal.py` | Journal page render, all API endpoints, error paths, trade linking |
| `test_analysis.py` | Analysis/reporting routes |
| `test_stats.py` | `compute_trade_stats` — PnL, fees, percent for debit/credit strategies |
| `test_import_trades_csv.py` | CSV import, schema creation, clear, code generation |
| `test_import_utils.py` | Header normalisation, money/int/datetime parsing |

**Test pattern**: each test class creates an isolated `tempfile` SQLite DB, patches `trade_app.DB_PATH`, sets `app.config['WTF_CSRF_ENABLED'] = False` (so test POSTs are not rejected by CSRF middleware), calls `init_db()`, uses Flask test client.

**Current coverage**: 85 % overall (62 tests passing).

| Module | Coverage |
|---|---|
| `tracker/services/stats.py` | 100 % |
| `tracker/routes/journal.py` | 100 % |
| `tracker/routes/reports.py` | 89 % |
| `tracker/routes/trades.py` | 82 % |
| `tracker/services/import_utils.py` | 82 % |
| `tracker/routes/accounts.py` | 81 % |
| `tracker/routes/home.py` | 78 % |
| `import_trades_csv.py` | 71 % |
| `app.py` | 48 % |

---

## 10. Data Flow

```
Browser
  │
  ▼ HTTP request
Flask route (routes/*.py)
  │
  ├─► get_db() ──► SQLite (data.db)
  │       │
  │       └─► sqlite3.Row results
  │
  ├─► compute_trade_stats() / fetch_entries()   [for trade detail / reports]
  │
  └─► render_template(...)  or  jsonify(...)
          │
          ▼
      HTML / JSON → Browser
```

Journal entries can reference a trade (`trade_id` FK). Analysis preferences are persisted between sessions via `app_settings`. Account selection is tracked in Flask's server-side session.

