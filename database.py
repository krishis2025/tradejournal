"""
DATABASE LAYER
All SQLite interactions. No business logic, no HTTP concerns.
"""

import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "journal.db")

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS portfolios (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL UNIQUE,
                description TEXT    NOT NULL DEFAULT '',
                color       TEXT    NOT NULL DEFAULT '#4fffb0',
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS trading_days (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                date         TEXT    NOT NULL,
                portfolio_id INTEGER REFERENCES portfolios(id) ON DELETE SET NULL,
                imported_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE(date, portfolio_id)
            );

            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                day_id      INTEGER NOT NULL REFERENCES trading_days(id) ON DELETE CASCADE,
                trade_num   INTEGER NOT NULL,
                direction   TEXT    NOT NULL,
                qty         INTEGER NOT NULL,
                avg_entry   REAL    NOT NULL,
                avg_exit    REAL    NOT NULL,
                pnl         REAL    NOT NULL,
                entry_time  TEXT    NOT NULL,
                exit_time   TEXT    NOT NULL,
                is_open     INTEGER NOT NULL DEFAULT 0,
                notes       TEXT    NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS fills (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id  INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
                fill_time TEXT    NOT NULL,
                side      TEXT    NOT NULL,
                qty       INTEGER NOT NULL,
                price     REAL    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trade_tags (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id  INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
                group_id  TEXT    NOT NULL,
                tag       TEXT    NOT NULL,
                UNIQUE(trade_id, group_id, tag)
            );

            CREATE INDEX IF NOT EXISTS idx_trades_day     ON trades(day_id);
            CREATE INDEX IF NOT EXISTS idx_fills_trade    ON fills(trade_id);
            CREATE INDEX IF NOT EXISTS idx_tags_trade     ON trade_tags(trade_id);
            CREATE INDEX IF NOT EXISTS idx_tags_group     ON trade_tags(group_id);
            CREATE INDEX IF NOT EXISTS idx_days_date      ON trading_days(date);
            CREATE INDEX IF NOT EXISTS idx_days_portfolio ON trading_days(portfolio_id);

            CREATE TABLE IF NOT EXISTS tag_config (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id  TEXT    NOT NULL,
                tag       TEXT    NOT NULL,
                position  INTEGER NOT NULL DEFAULT 0,
                enabled   INTEGER NOT NULL DEFAULT 1,
                UNIQUE(group_id, tag)
            );

            CREATE TABLE IF NOT EXISTS trade_images (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id    INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
                filename    TEXT    NOT NULL,
                caption     TEXT    NOT NULL DEFAULT '',
                uploaded_at TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_images_trade ON trade_images(trade_id);

            -- App-wide configuration (key-value)
            CREATE TABLE IF NOT EXISTS app_config (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );

            -- Live trade entries (used during trading hours)
            CREATE TABLE IF NOT EXISTS live_trades (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_id  INTEGER REFERENCES portfolios(id) ON DELETE SET NULL,
                status        TEXT    NOT NULL DEFAULT 'open',  -- open, closed, cancelled
                direction     TEXT    NOT NULL,                 -- Long, Short
                instrument    TEXT    NOT NULL DEFAULT 'MES',   -- MES, ES
                entry_price   REAL    NOT NULL,
                entry_time    TEXT    NOT NULL,                 -- HH:MM
                total_qty     INTEGER NOT NULL,
                mode          TEXT    NOT NULL DEFAULT 'full',  -- full, partials
                notes         TEXT    NOT NULL DEFAULT '',
                tags_json     TEXT    NOT NULL DEFAULT '{}',    -- JSON {group_id: [tag,...]}
                created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                closed_at     TEXT,
                realized_pnl  REAL    NOT NULL DEFAULT 0,
                journal_trade_id INTEGER                       -- links to trades.id after auto-save
            );

            -- Stop/TP levels for a live trade
            CREATE TABLE IF NOT EXISTS live_trade_levels (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                live_trade_id INTEGER NOT NULL REFERENCES live_trades(id) ON DELETE CASCADE,
                level_type    TEXT    NOT NULL,  -- stop, tp
                portion       INTEGER NOT NULL DEFAULT 1,  -- 1,2,3 for partials
                qty           INTEGER NOT NULL,
                price         REAL    NOT NULL,
                risk_dollars  REAL    NOT NULL DEFAULT 0,
                reward_dollars REAL   NOT NULL DEFAULT 0
            );

            -- Execution log entries (fills against live trade levels)
            CREATE TABLE IF NOT EXISTS live_trade_executions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                live_trade_id INTEGER NOT NULL REFERENCES live_trades(id) ON DELETE CASCADE,
                exec_type     TEXT    NOT NULL,  -- stop_hit, tp_hit, manual_exit
                portion       INTEGER NOT NULL DEFAULT 1,
                qty           INTEGER NOT NULL,
                price         REAL    NOT NULL,
                exec_time     TEXT    NOT NULL,  -- HH:MM
                pnl           REAL    NOT NULL DEFAULT 0,
                created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_live_levels ON live_trade_levels(live_trade_id);
            CREATE INDEX IF NOT EXISTS idx_live_execs  ON live_trade_executions(live_trade_id);
        """)
        # Safe migration for existing databases
        cols = [r[1] for r in conn.execute("PRAGMA table_info(trading_days)").fetchall()]
        if "portfolio_id" not in cols:
            conn.execute(
                "ALTER TABLE trading_days ADD COLUMN portfolio_id INTEGER REFERENCES portfolios(id) ON DELETE SET NULL"
            )


# ── Portfolios ────────────────────────────────────────────────────────────────

def get_all_portfolios():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT p.id, p.name, p.description, p.color, p.created_at,
                   COUNT(DISTINCT d.id)  as day_count,
                   COUNT(t.id)           as trade_count,
                   ROUND(SUM(t.pnl), 2)  as total_pnl
            FROM portfolios p
            LEFT JOIN trading_days d ON d.portfolio_id = p.id
            LEFT JOIN trades t       ON t.day_id = d.id
            GROUP BY p.id
            ORDER BY p.name
        """).fetchall()
        return [dict(r) for r in rows]


def get_portfolio_by_id(portfolio_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM portfolios WHERE id = ?", (portfolio_id,)).fetchone()
        return dict(row) if row else None


def create_portfolio(name, description="", color="#4fffb0"):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO portfolios (name, description, color) VALUES (?, ?, ?)",
            (name.strip(), description.strip(), color)
        )
        return cur.lastrowid


def update_portfolio(portfolio_id, name, description, color):
    with get_conn() as conn:
        conn.execute(
            "UPDATE portfolios SET name=?, description=?, color=? WHERE id=?",
            (name.strip(), description.strip(), color, portfolio_id)
        )


def delete_portfolio(portfolio_id):
    """Deletes portfolio; trading_days.portfolio_id becomes NULL (days kept)."""
    with get_conn() as conn:
        conn.execute("DELETE FROM portfolios WHERE id = ?", (portfolio_id,))


# ── Trading Days ──────────────────────────────────────────────────────────────

def get_all_days(date_from=None, date_to=None, portfolio_id=None):
    with get_conn() as conn:
        wheres, params = [], []
        if date_from:
            wheres.append("d.date >= ?"); params.append(date_from)
        if date_to:
            wheres.append("d.date <= ?"); params.append(date_to)
        if portfolio_id:
            wheres.append("d.portfolio_id = ?"); params.append(int(portfolio_id))
        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""

        rows = conn.execute(f"""
            SELECT d.id, d.date, d.imported_at, d.portfolio_id,
                   p.name  as portfolio_name,
                   p.color as portfolio_color,
                   COUNT(t.id)  as trade_count,
                   ROUND(SUM(t.pnl), 2) as total_pnl,
                   SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as wins
            FROM trading_days d
            LEFT JOIN portfolios p ON p.id = d.portfolio_id
            LEFT JOIN trades t     ON t.day_id = d.id
            {where_sql}
            GROUP BY d.id
            ORDER BY d.date DESC
        """, params).fetchall()
        return [dict(r) for r in rows]


def get_day_by_id(day_id):
    with get_conn() as conn:
        row = conn.execute("""
            SELECT d.*, p.name as portfolio_name, p.color as portfolio_color
            FROM trading_days d
            LEFT JOIN portfolios p ON p.id = d.portfolio_id
            WHERE d.id = ?
        """, (day_id,)).fetchone()
        return dict(row) if row else None


def get_day_by_date(date_str):
    """Backwards-compat: first matching day for a date."""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT d.*, p.name as portfolio_name, p.color as portfolio_color
            FROM trading_days d
            LEFT JOIN portfolios p ON p.id = d.portfolio_id
            WHERE d.date = ?
            ORDER BY d.id LIMIT 1
        """, (date_str,)).fetchone()
        return dict(row) if row else None


def get_day_by_date_portfolio(date_str, portfolio_id):
    with get_conn() as conn:
        if portfolio_id:
            row = conn.execute(
                "SELECT * FROM trading_days WHERE date = ? AND portfolio_id = ?",
                (date_str, int(portfolio_id))
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM trading_days WHERE date = ? AND portfolio_id IS NULL",
                (date_str,)
            ).fetchone()
        return dict(row) if row else None


def upsert_day(date_str, portfolio_id=None):
    with get_conn() as conn:
        if portfolio_id:
            conn.execute(
                "INSERT OR IGNORE INTO trading_days (date, portfolio_id) VALUES (?, ?)",
                (date_str, int(portfolio_id))
            )
            row = conn.execute(
                "SELECT id FROM trading_days WHERE date = ? AND portfolio_id = ?",
                (date_str, int(portfolio_id))
            ).fetchone()
        else:
            conn.execute(
                "INSERT OR IGNORE INTO trading_days (date, portfolio_id) VALUES (?, NULL)",
                (date_str,)
            )
            row = conn.execute(
                "SELECT id FROM trading_days WHERE date = ? AND portfolio_id IS NULL",
                (date_str,)
            ).fetchone()
        return row["id"]


def delete_day(day_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM trading_days WHERE id = ?", (day_id,))


# ── Trades ────────────────────────────────────────────────────────────────────

def get_trades_for_day(day_id):
    with get_conn() as conn:
        trades = conn.execute(
            "SELECT * FROM trades WHERE day_id = ? ORDER BY trade_num", (day_id,)
        ).fetchall()
        result = []
        for t in trades:
            td = dict(t)
            td["fills"] = [dict(f) for f in conn.execute(
                "SELECT * FROM fills WHERE trade_id = ? ORDER BY fill_time", (t["id"],)
            ).fetchall()]
            td["tags"] = {}
            for tag_row in conn.execute(
                "SELECT group_id, tag FROM trade_tags WHERE trade_id = ?", (t["id"],)
            ).fetchall():
                td["tags"].setdefault(tag_row["group_id"], []).append(tag_row["tag"])
            td["images"] = [dict(r) for r in conn.execute(
                "SELECT * FROM trade_images WHERE trade_id = ? ORDER BY uploaded_at", (t["id"],)
            ).fetchall()]
            result.append(td)
        return result


def get_trade_by_id(trade_id):
    with get_conn() as conn:
        t = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if not t:
            return None
        td = dict(t)
        td["fills"] = [dict(f) for f in conn.execute(
            "SELECT * FROM fills WHERE trade_id = ? ORDER BY fill_time", (trade_id,)
        ).fetchall()]
        td["tags"] = {}
        for tag_row in conn.execute(
            "SELECT group_id, tag FROM trade_tags WHERE trade_id = ?", (trade_id,)
        ).fetchall():
            td["tags"].setdefault(tag_row["group_id"], []).append(tag_row["tag"])
        day = conn.execute("""
            SELECT d.date, d.portfolio_id,
                   p.name as portfolio_name, p.color as portfolio_color
            FROM trading_days d
            LEFT JOIN portfolios p ON p.id = d.portfolio_id
            WHERE d.id = ?
        """, (td["day_id"],)).fetchone()
        if day:
            td["date"]            = day["date"]
            td["portfolio_id"]    = day["portfolio_id"]
            td["portfolio_name"]  = day["portfolio_name"]
            td["portfolio_color"] = day["portfolio_color"]
        td["images"] = get_trade_images(trade_id)
        return td


def insert_trade(day_id, trade_num, direction, qty, avg_entry, avg_exit, pnl, entry_time, exit_time, is_open=False):
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO trades
                (day_id, trade_num, direction, qty, avg_entry, avg_exit, pnl, entry_time, exit_time, is_open)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (day_id, trade_num, direction, qty, avg_entry, avg_exit, pnl, entry_time, exit_time, 1 if is_open else 0))
        return cur.lastrowid


def insert_fill(trade_id, fill_time, side, qty, price):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO fills (trade_id, fill_time, side, qty, price) VALUES (?, ?, ?, ?, ?)",
            (trade_id, fill_time, side, qty, price)
        )


def update_trade_notes(trade_id, notes):
    with get_conn() as conn:
        conn.execute("UPDATE trades SET notes = ? WHERE id = ?", (notes, trade_id))


def set_trade_tags(trade_id, group_id, tags):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM trade_tags WHERE trade_id = ? AND group_id = ?",
            (trade_id, group_id)
        )
        for tag in tags:
            conn.execute(
                "INSERT OR IGNORE INTO trade_tags (trade_id, group_id, tag) VALUES (?, ?, ?)",
                (trade_id, group_id, tag)
            )


# ── Trade Images ──────────────────────────────────────────────────────────────

def add_trade_image(trade_id, filename, caption=""):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO trade_images (trade_id, filename, caption) VALUES (?, ?, ?)",
            (trade_id, filename, caption)
        )
        return cur.lastrowid


def get_trade_images(trade_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trade_images WHERE trade_id = ? ORDER BY uploaded_at",
            (trade_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def update_image_caption(image_id, caption):
    with get_conn() as conn:
        conn.execute("UPDATE trade_images SET caption=? WHERE id=?", (caption, image_id))


def delete_trade_image(image_id):
    with get_conn() as conn:
        row = conn.execute("SELECT filename FROM trade_images WHERE id=?", (image_id,)).fetchone()
        filename = row["filename"] if row else None
        conn.execute("DELETE FROM trade_images WHERE id=?", (image_id,))
        return filename


# ── Tag Configuration ─────────────────────────────────────────────────────────

def get_tag_config():
    """Return {group_id: [tag, ...]} for enabled tags in order. None if no custom config."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT group_id, tag FROM tag_config WHERE enabled=1 ORDER BY group_id, position"
        ).fetchall()
        if not rows:
            return None
        result = {}
        for r in rows:
            result.setdefault(r["group_id"], []).append(r["tag"])
        return result


def save_tag_config(group_id, tags):
    """Replace all tags for a group with the provided ordered list."""
    with get_conn() as conn:
        conn.execute("DELETE FROM tag_config WHERE group_id = ?", (group_id,))
        for i, tag in enumerate(tags):
            tag = tag.strip()
            if tag:
                conn.execute(
                    "INSERT OR REPLACE INTO tag_config (group_id, tag, position, enabled) VALUES (?, ?, ?, 1)",
                    (group_id, tag, i)
                )


def reset_tag_config(group_id):
    """Delete custom config for a group so it falls back to app_logic defaults."""
    with get_conn() as conn:
        conn.execute("DELETE FROM tag_config WHERE group_id = ?", (group_id,))


# ── Analytics ─────────────────────────────────────────────────────────────────

def _compute_streaks(trades):
    """Compute current, best win, and worst loss streaks from ordered trade list."""
    if not trades:
        return {"current": 0, "current_type": None,
                "best_win": 0, "worst_loss": 0, "history": []}

    results = ["W" if t["pnl"] > 0 else ("L" if t["pnl"] < 0 else "B") for t in trades]

    cur_type  = results[-1]
    cur_count = 0
    for r in reversed(results):
        if r == cur_type:
            cur_count += 1
        else:
            break

    best_win = worst_loss = run = 0
    run_type = results[0]
    for r in results:
        if r == run_type:
            run += 1
        else:
            if run_type == "W": best_win   = max(best_win,   run)
            if run_type == "L": worst_loss = max(worst_loss, run)
            run_type, run = r, 1
    if run_type == "W": best_win   = max(best_win,   run)
    if run_type == "L": worst_loss = max(worst_loss, run)

    # Last 20 results for the sparkline
    history = results[-20:]

    return {
        "current":      cur_count if cur_type != "B" else 0,
        "current_type": cur_type,
        "best_win":     best_win,
        "worst_loss":   worst_loss,
        "history":      history,
    }


def get_analytics(portfolio_id=None):
    with get_conn() as conn:
        if portfolio_id:
            pid = int(portfolio_id)
            p_filter_tag  = f"AND d.portfolio_id = {pid}"
            p_filter_day  = f"WHERE d.portfolio_id = {pid}"
        else:
            p_filter_tag = p_filter_day = ""

        tag_stats = conn.execute(f"""
            SELECT tt.group_id, tt.tag,
                   COUNT(t.id) AS total,
                   SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
                   ROUND(AVG(t.pnl), 2)  AS avg_pnl,
                   ROUND(SUM(t.pnl), 2)  AS total_pnl,
                   ROUND(100.0 * SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) / COUNT(t.id), 1) AS win_rate
            FROM trade_tags tt
            JOIN trades t        ON t.id = tt.trade_id
            JOIN trading_days d  ON d.id = t.day_id
            WHERE 1=1 {p_filter_tag}
            GROUP BY tt.group_id, tt.tag
            ORDER BY tt.group_id, avg_pnl DESC
        """).fetchall()

        time_stats = conn.execute(f"""
            SELECT CAST(SUBSTR(t.entry_time, 1, 2) AS INTEGER) AS hour,
                   COUNT(*) AS total,
                   ROUND(AVG(t.pnl), 2) AS avg_pnl,
                   SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins
            FROM trades t
            JOIN trading_days d ON d.id = t.day_id
            {p_filter_day}
            GROUP BY hour ORDER BY hour
        """).fetchall()

        daily = conn.execute(f"""
            SELECT d.date,
                   COUNT(t.id) AS trades,
                   ROUND(SUM(t.pnl), 2) AS pnl,
                   SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins
            FROM trading_days d
            JOIN trades t ON t.day_id = d.id
            {p_filter_day}
            GROUP BY d.id ORDER BY d.date
        """).fetchall()

        overall = conn.execute(f"""
            SELECT COUNT(*) as total_trades,
                   ROUND(SUM(t.pnl), 2) as total_pnl,
                   ROUND(AVG(t.pnl), 2) as avg_pnl,
                   SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as wins,
                   ROUND(MAX(t.pnl), 2) as best_trade,
                   ROUND(MIN(t.pnl), 2) as worst_trade
            FROM trades t
            JOIN trading_days d ON d.id = t.day_id
            {p_filter_day}
        """).fetchone()

        dow_stats = conn.execute(f"""
            SELECT CAST(STRFTIME('%w', d.date) AS INTEGER) AS dow,
                   COUNT(t.id)  AS total,
                   ROUND(SUM(t.pnl),  2) AS total_pnl,
                   ROUND(AVG(t.pnl),  2) AS avg_pnl,
                   SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins
            FROM trades t
            JOIN trading_days d ON d.id = t.day_id
            {p_filter_day}
            GROUP BY dow ORDER BY dow
        """).fetchall()

        # Streak: fetch all trades ordered by date+entry_time to compute W/L runs
        all_trades = conn.execute(f"""
            SELECT t.pnl, d.date
            FROM trades t
            JOIN trading_days d ON d.id = t.day_id
            {p_filter_day}
            ORDER BY d.date, t.entry_time
        """).fetchall()

        # Compute current streak and best/worst streaks
        streak_data = _compute_streaks([dict(r) for r in all_trades])

        return {
            "tag_stats":  [dict(r) for r in tag_stats],
            "time_stats": [dict(r) for r in time_stats],
            "daily":      [dict(r) for r in daily],
            "overall":    dict(overall) if overall else {},
            "dow_stats":  [dict(r) for r in dow_stats],
            "streaks":    streak_data,
        }


# ── App Configuration ────────────────────────────────────────────────────────

def get_config(key, default=""):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM app_config WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

def set_config(key, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO app_config (key, value) VALUES (?, ?)",
            (key, str(value))
        )

def get_all_config():
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM app_config").fetchall()
        return {r["key"]: r["value"] for r in rows}


# ── Live Trades ──────────────────────────────────────────────────────────────

def create_live_trade(portfolio_id, direction, instrument, entry_price, entry_time,
                      total_qty, mode, notes="", tags_json="{}"):
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO live_trades
                (portfolio_id, direction, instrument, entry_price, entry_time,
                 total_qty, mode, notes, tags_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (portfolio_id, direction, instrument, entry_price, entry_time,
              total_qty, mode, notes, tags_json))
        return cur.lastrowid


def get_live_trade(live_trade_id):
    with get_conn() as conn:
        row = conn.execute("""
            SELECT lt.*, p.name as portfolio_name, p.color as portfolio_color
            FROM live_trades lt
            LEFT JOIN portfolios p ON p.id = lt.portfolio_id
            WHERE lt.id = ?
        """, (live_trade_id,)).fetchone()
        if not row:
            return None
        td = dict(row)
        td["levels"] = [dict(r) for r in conn.execute(
            "SELECT * FROM live_trade_levels WHERE live_trade_id = ? ORDER BY level_type, portion",
            (live_trade_id,)
        ).fetchall()]
        td["executions"] = [dict(r) for r in conn.execute(
            "SELECT * FROM live_trade_executions WHERE live_trade_id = ? ORDER BY created_at",
            (live_trade_id,)
        ).fetchall()]
        return td


def get_all_live_trades(status=None, date_from=None, date_to=None):
    """
    Get live trades with optional status and date range filters.
    date_from / date_to are ISO date strings (YYYY-MM-DD).
    """
    with get_conn() as conn:
        conditions = []
        params = []
        if status:
            conditions.append("lt.status = ?")
            params.append(status)
        if date_from:
            conditions.append("date(lt.created_at, 'localtime') >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("date(lt.created_at, 'localtime') <= ?")
            params.append(date_to)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = conn.execute(f"""
            SELECT lt.*, p.name as portfolio_name, p.color as portfolio_color
            FROM live_trades lt
            LEFT JOIN portfolios p ON p.id = lt.portfolio_id
            {where}
            ORDER BY lt.created_at DESC
        """, params).fetchall()
        return [dict(r) for r in rows]


def update_live_trade(live_trade_id, **kwargs):
    with get_conn() as conn:
        sets = []
        vals = []
        for k, v in kwargs.items():
            sets.append(f"{k} = ?")
            vals.append(v)
        vals.append(live_trade_id)
        conn.execute(
            f"UPDATE live_trades SET {', '.join(sets)} WHERE id = ?", vals
        )


def delete_live_trade(live_trade_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM live_trades WHERE id = ?", (live_trade_id,))


def set_live_trade_levels(live_trade_id, levels):
    """Replace all levels for a live trade. levels = [{level_type, portion, qty, price, risk_dollars, reward_dollars}]"""
    with get_conn() as conn:
        conn.execute("DELETE FROM live_trade_levels WHERE live_trade_id = ?", (live_trade_id,))
        for lv in levels:
            conn.execute("""
                INSERT INTO live_trade_levels
                    (live_trade_id, level_type, portion, qty, price, risk_dollars, reward_dollars)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (live_trade_id, lv["level_type"], lv["portion"], lv["qty"],
                  lv["price"], lv.get("risk_dollars", 0), lv.get("reward_dollars", 0)))


def add_live_trade_execution(live_trade_id, exec_type, portion, qty, price, exec_time, pnl):
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO live_trade_executions
                (live_trade_id, exec_type, portion, qty, price, exec_time, pnl)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (live_trade_id, exec_type, portion, qty, price, exec_time, pnl))
        return cur.lastrowid


def delete_live_trade_execution(exec_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM live_trade_executions WHERE id = ?", (exec_id,))
