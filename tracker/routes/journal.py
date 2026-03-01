
from flask import request, jsonify
from datetime import datetime

def register_journal_routes(app, get_db):
    @app.route('/journal/entries', methods=['GET'])
    def journal_get_entries():
        with get_db() as conn:
            rows = conn.execute(
                '''
                SELECT j.*, t.symbol, t.option_type, t.trade_code,
                    (SELECT SUM(CASE WHEN e.side = "BUY" THEN e.contracts ELSE 0 END) FROM entries e WHERE e.trade_id = t.id) AS num_options,
                    (SELECT SUM(CASE WHEN e.side = "SELL" THEN e.contracts * e.price ELSE 0 END) - SUM(CASE WHEN e.side = "BUY" THEN e.contracts * e.price ELSE 0 END) FROM entries e WHERE e.trade_id = t.id) AS pnl
                FROM journal j
                LEFT JOIN trades t ON j.trade_id = t.id
                ORDER BY j.date DESC
                '''
            ).fetchall()
            return jsonify([dict(row) for row in rows])

    @app.route('/journal/entry', methods=['POST'])
    def journal_add_entry():
        data = request.get_json() or {}
        date_raw = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        try:
            date_val = datetime.strptime(date_raw, '%Y-%m-%d').strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            return jsonify({'status': 'error', 'message': 'Invalid date format. Use YYYY-MM-DD.'}), 400
        text = (data.get('text') or '').strip()
        if not text:
            return jsonify({'status': 'error', 'message': 'Entry text is required.'}), 400
        title = data.get('title', '')
        tags = data.get('tags', '')
        trade_id = data.get('trade_id')
        with get_db() as conn:
            conn.execute(
                'INSERT INTO journal (date, title, text, tags, trade_id) VALUES (?, ?, ?, ?, ?)',
                (date_val, title, text, tags, trade_id)
            )
            conn.commit()
        return jsonify({'status': 'success'})

    @app.route('/journal/entries/<string:entry_date>', methods=['GET'])
    def journal_get_entries_for_date(entry_date):
        with get_db() as conn:
            rows = conn.execute(
                '''
                SELECT j.*, t.symbol, t.option_type, t.trade_code,
                    (SELECT SUM(CASE WHEN e.side = "BUY" THEN e.contracts ELSE 0 END) FROM entries e WHERE e.trade_id = t.id) AS num_options,
                    (SELECT SUM(CASE WHEN e.side = "SELL" THEN e.contracts * e.price ELSE 0 END) - SUM(CASE WHEN e.side = "BUY" THEN e.contracts * e.price ELSE 0 END) FROM entries e WHERE e.trade_id = t.id) AS pnl
                FROM journal j
                LEFT JOIN trades t ON j.trade_id = t.id
                WHERE j.date = ? ORDER BY j.id ASC
                ''',
                (entry_date,)
            ).fetchall()
            return jsonify([dict(row) for row in rows])

    @app.route('/journal/closed_trades_today', methods=['GET'])
    def journal_closed_trades_today():
        today = datetime.now().strftime('%Y-%m-%d')
        with get_db() as conn:
            rows = conn.execute(
                'SELECT id, trade_code, symbol FROM trades WHERE status = "CLOSED" AND closed_at LIKE ?',
                (today + '%',)
            ).fetchall()
            return jsonify([dict(row) for row in rows])
