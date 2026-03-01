import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data.db"
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

trades = cur.execute('SELECT COUNT(*) FROM trades').fetchone()[0]
balances = cur.execute('SELECT COUNT(*) FROM daily_balances').fetchone()[0]

print(f'Trades: {trades}')
print(f'Daily Balances: {balances}')

if trades > 0:
    print('\nSample trades:')
    rows = cur.execute('SELECT id, trade_code, closed_at FROM trades LIMIT 5').fetchall()
    for r in rows:
        print(f'  {r}')

conn.close()
