# Options Trade Tracker — Copilot Instructions

Flask + SQLite options trading journal. No ORM, no Blueprints.

## Stack

- **Flask 3** — manual route registration; no Blueprints
- **SQLite** — via stdlib `sqlite3`; always use `sqlite3.Row` row factory
- **flask-wtf** — CSRF protection via `CSRFProtect(app)`
- **Plotly** — server-side `json.dumps(..., cls=pu.PlotlyJSONEncoder)`, rendered client-side
- **pytest** — 62 tests, 85% coverage

## Architecture

- `app.py` — app factory, `get_db()` contextmanager, `init_db()`, route wiring, CLI entry point
- `tracker/routes/` — one file per feature area; each exports `register_*_routes(app, get_db, ...)`
- `tracker/services/stats.py` — `compute_trade_stats(entries, fee_per_contract)` → pure function
- `tracker/services/import_utils.py` — CSV parsing helpers
- `templates/` — all extend `layout.html`; Jinja2 filters: `money`, `pct`

## Key Patterns

### Database access
`get_db()` is a `@contextmanager` — always use it as `with get_db() as conn:`. It auto-commits on success, rolls back on exception, and always closes. Never call `conn.commit()` manually inside a `with get_db()` block.

```python
with get_db() as conn:
    conn.execute("INSERT INTO ...", (val,))
```

### Parameterized queries only
Never use f-strings or string concatenation to build SQL. Always use `?` placeholders.

### Route registration
Each route module receives its dependencies as function arguments — never import `get_db` or `app` directly inside route modules.

```python
def register_trade_routes(app, get_db, fetch_entries, compute_trade_stats, ...):
    @app.route("/trade/create", methods=["POST"])
    def create_trade():
        ...
```

### CSRF
All POST forms must include `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`.
JSON fetch POSTs must send `X-CSRFToken` from `<meta name="csrf-token">`.

## Testing

Each test class:
1. Creates an isolated `tempfile` SQLite DB
2. Patches `trade_app.DB_PATH`
3. Sets `trade_app.app.config['WTF_CSRF_ENABLED'] = False`
4. Calls `trade_app.init_db()`
5. Creates `trade_app.app.test_client()`

Insert fixture data with `sqlite3.connect(self.db_path)` directly — not via `get_db()`.

## Environment Variables

| Variable | Default | Notes |
|---|---|---|
| `TRADETRACKER_SECRET_KEY` | `dev-secret-key` | Change in production |
| `FLASK_DEBUG` | `1` | Set to `0` in production |

## What Not To Do

- Don't add an ORM (SQLAlchemy etc.) — raw `sqlite3` is intentional
- Don't use Flask Blueprints — manual `register_*_routes` pattern is intentional
- Don't use `conn.commit()` inside `with get_db() as conn:` blocks (the contextmanager handles it)
- Don't use `| safe` in templates on user-controlled data — use `| tojson` instead
