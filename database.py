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


def _migrate_portfolio_to_account(conn):
    """Rename portfolios table → accounts, portfolio_id columns → account_id."""
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if "portfolios" not in tables or "accounts" in tables:
        return  # Already migrated or fresh DB

    # 1. Create accounts table and copy data
    conn.execute("""
        CREATE TABLE accounts (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            name                TEXT    NOT NULL UNIQUE,
            description         TEXT    NOT NULL DEFAULT '',
            color               TEXT    NOT NULL DEFAULT '#4fffb0',
            created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
            account_size        REAL,
            default_qty         INTEGER,
            default_instrument  TEXT,
            is_primary          INTEGER NOT NULL DEFAULT 0,
            risk_per_trade_pct  REAL
        )
    """)
    # Get columns that exist in portfolios to handle partial migrations
    port_cols = [r[1] for r in conn.execute("PRAGMA table_info(portfolios)").fetchall()]
    select_cols = ["id", "name", "description", "color", "created_at"]
    for c in ["account_size", "default_qty", "default_instrument", "is_primary", "risk_per_trade_pct"]:
        if c in port_cols:
            select_cols.append(c)
    insert_cols = select_cols[:]
    conn.execute(f"INSERT INTO accounts ({','.join(insert_cols)}) SELECT {','.join(select_cols)} FROM portfolios")

    # 2. Migrate trading_days: portfolio_id → account_id
    conn.execute("""
        CREATE TABLE trading_days_new (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT    NOT NULL,
            account_id  INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
            imported_at TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE(date, account_id)
        )
    """)
    conn.execute("INSERT INTO trading_days_new (id, date, account_id, imported_at) SELECT id, date, portfolio_id, imported_at FROM trading_days")
    conn.execute("DROP TABLE trading_days")
    conn.execute("ALTER TABLE trading_days_new RENAME TO trading_days")

    # 3. Migrate live_trades: portfolio_id → account_id
    lt_cols = [r[1] for r in conn.execute("PRAGMA table_info(live_trades)").fetchall()]
    if "portfolio_id" in lt_cols:
        # Build column list dynamically
        new_cols = [c if c != "portfolio_id" else "account_id" for c in lt_cols]
        old_cols_str = ",".join(lt_cols)
        new_cols_str = ",".join(new_cols)
        conn.execute(f"""
            CREATE TABLE live_trades_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id    INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
                status        TEXT    NOT NULL DEFAULT 'open',
                direction     TEXT    NOT NULL,
                instrument    TEXT    NOT NULL DEFAULT 'MES',
                entry_price   REAL    NOT NULL,
                entry_time    TEXT    NOT NULL,
                total_qty     INTEGER NOT NULL,
                mode          TEXT    NOT NULL DEFAULT 'full',
                notes         TEXT    NOT NULL DEFAULT '',
                tags_json     TEXT    NOT NULL DEFAULT '{{}}',
                created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                closed_at     TEXT,
                realized_pnl  REAL    NOT NULL DEFAULT 0,
                journal_trade_id INTEGER,
                notes_monitoring TEXT NOT NULL DEFAULT '',
                notes_exit    TEXT    NOT NULL DEFAULT ''
            )
        """)
        conn.execute(f"INSERT INTO live_trades_new ({new_cols_str}) SELECT {old_cols_str} FROM live_trades")
        conn.execute("DROP TABLE live_trades")
        conn.execute("ALTER TABLE live_trades_new RENAME TO live_trades")

    # 4. Migrate shadow_trades: portfolio_id → account_id
    if "shadow_trades" in tables:
        st_cols = [r[1] for r in conn.execute("PRAGMA table_info(shadow_trades)").fetchall()]
        if "portfolio_id" in st_cols:
            conn.execute("""
                CREATE TABLE shadow_trades_new (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_trade_id     INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
                    account_id          INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    projected_qty       INTEGER NOT NULL,
                    projected_instrument TEXT NOT NULL DEFAULT 'MES',
                    projected_pnl       REAL NOT NULL,
                    UNIQUE(source_trade_id, account_id)
                )
            """)
            conn.execute("INSERT INTO shadow_trades_new (id, source_trade_id, account_id, projected_qty, projected_instrument, projected_pnl) SELECT id, source_trade_id, portfolio_id, projected_qty, projected_instrument, projected_pnl FROM shadow_trades")
            conn.execute("DROP TABLE shadow_trades")
            conn.execute("ALTER TABLE shadow_trades_new RENAME TO shadow_trades")

    # 5. Drop old portfolios table
    conn.execute("DROP TABLE portfolios")

    # 6. Recreate indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_days_account ON trading_days(account_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_shadow_source ON shadow_trades(source_trade_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_shadow_account ON shadow_trades(account_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_live_levels ON live_trade_levels(live_trade_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_live_execs ON live_trade_executions(live_trade_id)")


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
        # Run migration from portfolio → account if needed
        _migrate_portfolio_to_account(conn)

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL UNIQUE,
                description TEXT    NOT NULL DEFAULT '',
                color       TEXT    NOT NULL DEFAULT '#4fffb0',
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS trading_days (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                date         TEXT    NOT NULL,
                account_id   INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
                imported_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE(date, account_id)
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
                notes       TEXT    NOT NULL DEFAULT '',
                execution_json TEXT              -- JSON: levels, executions from live trade (NULL for imports)
            );

            CREATE TABLE IF NOT EXISTS fills (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id  INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
                fill_time TEXT    NOT NULL,
                side      TEXT    NOT NULL,
                qty       INTEGER NOT NULL,
                price     REAL    NOT NULL,
                exit_type TEXT                    -- tp_hit, stop_hit, manual_exit, or NULL (imports)
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
            CREATE INDEX IF NOT EXISTS idx_days_account ON trading_days(account_id);

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
                account_id    INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
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
        if "account_id" not in cols:
            conn.execute(
                "ALTER TABLE trading_days ADD COLUMN account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL"
            )
        # Migration: add exit_type to fills
        fill_cols = [r[1] for r in conn.execute("PRAGMA table_info(fills)").fetchall()]
        if "exit_type" not in fill_cols:
            conn.execute("ALTER TABLE fills ADD COLUMN exit_type TEXT")
        # Migration: add execution_json to trades
        trade_cols = [r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()]
        if "execution_json" not in trade_cols:
            conn.execute("ALTER TABLE trades ADD COLUMN execution_json TEXT")

        # Migration: add notes_monitoring and notes_exit to trades table
        trade_cols = [r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()]
        if "notes_monitoring" not in trade_cols:
            conn.execute("ALTER TABLE trades ADD COLUMN notes_monitoring TEXT NOT NULL DEFAULT ''")
        if "notes_exit" not in trade_cols:
            conn.execute("ALTER TABLE trades ADD COLUMN notes_exit TEXT NOT NULL DEFAULT ''")

        # Migration: add notes_monitoring and notes_exit to live_trades table
        lt_cols2 = [r[1] for r in conn.execute("PRAGMA table_info(live_trades)").fetchall()]
        if "notes_monitoring" not in lt_cols2:
            conn.execute("ALTER TABLE live_trades ADD COLUMN notes_monitoring TEXT NOT NULL DEFAULT ''")
        if "notes_exit" not in lt_cols2:
            conn.execute("ALTER TABLE live_trades ADD COLUMN notes_exit TEXT NOT NULL DEFAULT ''")

        # Migration: add account profile columns to accounts
        acct_cols = [r[1] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()]
        if "account_size" not in acct_cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN account_size REAL")
        if "default_qty" not in acct_cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN default_qty INTEGER")
        if "default_instrument" not in acct_cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN default_instrument TEXT")
        if "is_primary" not in acct_cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN is_primary INTEGER NOT NULL DEFAULT 0")
        if "risk_per_trade_pct" not in acct_cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN risk_per_trade_pct REAL")

        # Migration: create shadow_trades table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shadow_trades (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                source_trade_id     INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
                account_id          INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                projected_qty       INTEGER NOT NULL,
                projected_instrument TEXT NOT NULL DEFAULT 'MES',
                projected_pnl       REAL NOT NULL,
                UNIQUE(source_trade_id, account_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shadow_source ON shadow_trades(source_trade_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shadow_account ON shadow_trades(account_id)")


# ── Accounts ─────────────────────────────────────────────────────────────────

def get_all_accounts():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT a.id, a.name, a.description, a.color, a.created_at,
                   a.account_size, a.default_qty, a.default_instrument,
                   a.is_primary, a.risk_per_trade_pct,
                   COUNT(DISTINCT d.id)  as day_count,
                   COUNT(t.id)           as trade_count,
                   ROUND(SUM(t.pnl), 2)  as total_pnl
            FROM accounts a
            LEFT JOIN trading_days d ON d.account_id = a.id
            LEFT JOIN trades t       ON t.day_id = d.id
            GROUP BY a.id
            ORDER BY a.is_primary DESC, a.name
        """).fetchall()
        return [dict(r) for r in rows]


def get_account_by_id(account_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return dict(row) if row else None


def create_account(name, description="", color="#4fffb0",
                   account_size=None, default_qty=None, default_instrument=None,
                   is_primary=0, risk_per_trade_pct=None):
    with get_conn() as conn:
        if is_primary:
            conn.execute("UPDATE accounts SET is_primary = 0 WHERE is_primary = 1")
        cur = conn.execute(
            """INSERT INTO accounts
               (name, description, color, account_size, default_qty, default_instrument, is_primary, risk_per_trade_pct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (name.strip(), description.strip(), color,
             account_size, default_qty, default_instrument, is_primary, risk_per_trade_pct)
        )
        return cur.lastrowid


def update_account(account_id, name, description, color,
                   account_size=None, default_qty=None, default_instrument=None,
                   is_primary=0, risk_per_trade_pct=None):
    with get_conn() as conn:
        if is_primary:
            conn.execute("UPDATE accounts SET is_primary = 0 WHERE is_primary = 1")
        conn.execute(
            """UPDATE accounts SET name=?, description=?, color=?,
               account_size=?, default_qty=?, default_instrument=?,
               is_primary=?, risk_per_trade_pct=?
               WHERE id=?""",
            (name.strip(), description.strip(), color,
             account_size, default_qty, default_instrument, is_primary, risk_per_trade_pct,
             account_id)
        )


def delete_account(account_id):
    """Deletes account; trading_days.account_id becomes NULL (days kept)."""
    with get_conn() as conn:
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))


# ── Trading Days ──────────────────────────────────────────────────────────────

def get_all_days(date_from=None, date_to=None, account_id=None):
    with get_conn() as conn:
        wheres, params = [], []
        if date_from:
            wheres.append("d.date >= ?"); params.append(date_from)
        if date_to:
            wheres.append("d.date <= ?"); params.append(date_to)
        if account_id:
            wheres.append("d.account_id = ?"); params.append(int(account_id))
        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""

        rows = conn.execute(f"""
            SELECT d.id, d.date, d.imported_at, d.account_id,
                   a.name  as account_name,
                   a.color as account_color,
                   COUNT(t.id)  as trade_count,
                   ROUND(COALESCE(SUM(t.pnl), 0), 2) as total_pnl,
                   SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as wins
            FROM trading_days d
            LEFT JOIN accounts a ON a.id = d.account_id
            LEFT JOIN trades t     ON t.day_id = d.id
            {where_sql}
            GROUP BY d.id
            ORDER BY d.date DESC
        """, params).fetchall()
        return [dict(r) for r in rows]


def get_day_by_id(day_id):
    with get_conn() as conn:
        row = conn.execute("""
            SELECT d.*, a.name as account_name, a.color as account_color
            FROM trading_days d
            LEFT JOIN accounts a ON a.id = d.account_id
            WHERE d.id = ?
        """, (day_id,)).fetchone()
        return dict(row) if row else None


def get_day_by_date(date_str):
    """Backwards-compat: first matching day for a date."""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT d.*, a.name as account_name, a.color as account_color
            FROM trading_days d
            LEFT JOIN accounts a ON a.id = d.account_id
            WHERE d.date = ?
            ORDER BY d.id LIMIT 1
        """, (date_str,)).fetchone()
        return dict(row) if row else None


def get_day_by_date_account(date_str, account_id):
    with get_conn() as conn:
        if account_id:
            row = conn.execute(
                "SELECT * FROM trading_days WHERE date = ? AND account_id = ?",
                (date_str, int(account_id))
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM trading_days WHERE date = ? AND account_id IS NULL",
                (date_str,)
            ).fetchone()
        return dict(row) if row else None


def upsert_day(date_str, account_id=None):
    with get_conn() as conn:
        if account_id:
            conn.execute(
                "INSERT OR IGNORE INTO trading_days (date, account_id) VALUES (?, ?)",
                (date_str, int(account_id))
            )
            row = conn.execute(
                "SELECT id FROM trading_days WHERE date = ? AND account_id = ?",
                (date_str, int(account_id))
            ).fetchone()
        else:
            conn.execute(
                "INSERT OR IGNORE INTO trading_days (date, account_id) VALUES (?, NULL)",
                (date_str,)
            )
            row = conn.execute(
                "SELECT id FROM trading_days WHERE date = ? AND account_id IS NULL",
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
            SELECT d.date, d.account_id,
                   a.name as account_name, a.color as account_color
            FROM trading_days d
            LEFT JOIN accounts a ON a.id = d.account_id
            WHERE d.id = ?
        """, (td["day_id"],)).fetchone()
        if day:
            td["date"]            = day["date"]
            td["account_id"]      = day["account_id"]
            td["account_name"]  = day["account_name"]
            td["account_color"] = day["account_color"]
        td["images"] = get_trade_images(trade_id)
        return td


def insert_trade(day_id, trade_num, direction, qty, avg_entry, avg_exit, pnl, entry_time, exit_time, is_open=False, execution_json=None):
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO trades
                (day_id, trade_num, direction, qty, avg_entry, avg_exit, pnl, entry_time, exit_time, is_open, execution_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (day_id, trade_num, direction, qty, avg_entry, avg_exit, pnl, entry_time, exit_time, 1 if is_open else 0, execution_json))
        return cur.lastrowid


def insert_fill(trade_id, fill_time, side, qty, price, exit_type=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO fills (trade_id, fill_time, side, qty, price, exit_type) VALUES (?, ?, ?, ?, ?, ?)",
            (trade_id, fill_time, side, qty, price, exit_type)
        )


def update_trade_notes(trade_id, notes, notes_monitoring=None, notes_exit=None):
    with get_conn() as conn:
        sets = ["notes = ?"]
        vals = [notes]
        if notes_monitoring is not None:
            sets.append("notes_monitoring = ?")
            vals.append(notes_monitoring)
        if notes_exit is not None:
            sets.append("notes_exit = ?")
            vals.append(notes_exit)
        vals.append(trade_id)
        conn.execute(f"UPDATE trades SET {', '.join(sets)} WHERE id = ?", vals)


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


def get_analytics(account_id=None, date_from=None, date_to=None):
    with get_conn() as conn:
        # Build filter clauses
        conditions_tag = []   # for queries that already have WHERE (tag joins)
        conditions_day = []   # for queries where trading_days is the base

        if account_id:
            aid = int(account_id)
            conditions_tag.append(f"d.account_id = {aid}")
            conditions_day.append(f"d.account_id = {aid}")
        if date_from:
            conditions_tag.append("d.date >= ?")
            conditions_day.append("d.date >= ?")
        if date_to:
            conditions_tag.append("d.date <= ?")
            conditions_day.append("d.date <= ?")

        # Parameter lists (date_from/date_to only — account_id is inlined)
        date_params = []
        if date_from: date_params.append(date_from)
        if date_to:   date_params.append(date_to)

        p_filter_tag = (" AND " + " AND ".join(conditions_tag)) if conditions_tag else ""
        p_filter_day = ("WHERE " + " AND ".join(conditions_day)) if conditions_day else ""

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
        """, date_params).fetchall()

        time_stats = conn.execute(f"""
            SELECT CAST(SUBSTR(t.entry_time, 1, 2) AS INTEGER) AS hour,
                   COUNT(*) AS total,
                   ROUND(AVG(t.pnl), 2) AS avg_pnl,
                   SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins
            FROM trades t
            JOIN trading_days d ON d.id = t.day_id
            {p_filter_day}
            GROUP BY hour ORDER BY hour
        """, date_params).fetchall()

        daily = conn.execute(f"""
            SELECT d.date,
                   COUNT(t.id) AS trades,
                   ROUND(SUM(t.pnl), 2) AS pnl,
                   SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins
            FROM trading_days d
            JOIN trades t ON t.day_id = d.id
            {p_filter_day}
            GROUP BY d.id ORDER BY d.date
        """, date_params).fetchall()

        overall_row = conn.execute(f"""
            SELECT COUNT(*) as total_trades,
                   ROUND(COALESCE(SUM(t.pnl), 0), 2) as total_pnl,
                   ROUND(AVG(t.pnl), 2) as avg_pnl,
                   SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as wins,
                   ROUND(MAX(t.pnl), 2) as best_trade,
                   ROUND(MIN(t.pnl), 2) as worst_trade,
                   ROUND(AVG(CASE WHEN t.pnl > 0 THEN t.pnl END), 2) as avg_win,
                   ROUND(AVG(CASE WHEN t.pnl < 0 THEN t.pnl END), 2) as avg_loss,
                   ROUND(SUM(CASE WHEN t.pnl > 0 THEN t.pnl ELSE 0 END), 2) as gross_profit,
                   ROUND(SUM(CASE WHEN t.pnl < 0 THEN ABS(t.pnl) ELSE 0 END), 2) as gross_loss
            FROM trades t
            JOIN trading_days d ON d.id = t.day_id
            {p_filter_day}
        """, date_params).fetchone()

        overall = dict(overall_row) if overall_row else {}

        # Compute derived KPIs
        if overall.get("total_trades"):
            total = overall["total_trades"]
            wins = overall["wins"] or 0
            avg_win = overall["avg_win"] or 0
            avg_loss = abs(overall["avg_loss"] or 0)
            win_rate = wins / total
            loss_rate = 1 - win_rate

            overall["win_loss_ratio"] = round(avg_win / avg_loss, 2) if avg_loss else 0
            overall["expectancy"] = round((win_rate * avg_win) - (loss_rate * avg_loss), 2)
            overall["profit_factor"] = round(overall["gross_profit"] / overall["gross_loss"], 2) if overall["gross_loss"] else 0

            # Count distinct trading days
            day_count = conn.execute(f"""
                SELECT COUNT(DISTINCT d.id)
                FROM trading_days d JOIN trades t ON t.day_id = d.id
                {p_filter_day}
            """, date_params).fetchone()[0]
            overall["total_days"] = day_count

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
        """, date_params).fetchall()

        # All trades ordered by date+time — used for streaks, equity curve, duration
        all_trades = conn.execute(f"""
            SELECT t.id, t.pnl, t.entry_time, t.exit_time, t.direction, t.qty,
                   t.avg_entry, t.avg_exit, t.execution_json,
                   d.date
            FROM trades t
            JOIN trading_days d ON d.id = t.day_id
            {p_filter_day}
            ORDER BY d.date, t.entry_time
        """, date_params).fetchall()
        all_trades_list = [dict(r) for r in all_trades]

        # Streaks
        streak_data = _compute_streaks(all_trades_list)

        # Equity curve: cumulative P&L per trade
        equity_curve = []
        cumulative = 0
        for t in all_trades_list:
            cumulative = round(cumulative + t["pnl"], 2)
            equity_curve.append({
                "date": t["date"],
                "time": t["entry_time"],
                "pnl": t["pnl"],
                "cumulative": cumulative,
            })

        # Drawdown analysis from equity curve
        drawdown = _compute_drawdown(equity_curve)

        # Trade duration stats (entry_time → exit_time in minutes)
        duration_stats = _compute_duration_stats(all_trades_list)

        # Calendar data — daily P&L keyed by date (reuse daily query)
        calendar = [dict(r) for r in daily]

        # Tag correlation analysis — find co-occurring tag combos across groups
        tag_correlations = _compute_tag_correlations(conn, p_filter_tag, date_params, overall)

        return {
            "tag_stats":    [dict(r) for r in tag_stats],
            "time_stats":   [dict(r) for r in time_stats],
            "daily":        [dict(r) for r in daily],
            "overall":      overall,
            "dow_stats":    [dict(r) for r in dow_stats],
            "streaks":      streak_data,
            "equity_curve": equity_curve,
            "drawdown":     drawdown,
            "duration_stats": duration_stats,
            "calendar":     calendar,
            "tag_correlations": tag_correlations,
        }


def _compute_tag_correlations(conn, p_filter_tag, date_params, overall):
    """Find co-occurring tag combinations across different groups and their P&L impact."""
    overall_wr = 0
    if overall and overall.get("total_trades") and overall.get("wins"):
        overall_wr = round(overall["wins"] / overall["total_trades"] * 100, 1)

    try:
        rows = conn.execute(f"""
            SELECT t1.group_id AS group_a, t1.tag AS tag_a,
                   t2.group_id AS group_b, t2.tag AS tag_b,
                   COUNT(DISTINCT t1.trade_id) AS trades,
                   SUM(CASE WHEN tr.pnl > 0 THEN 1 ELSE 0 END) AS wins,
                   ROUND(AVG(tr.pnl), 2) AS avg_pnl,
                   ROUND(SUM(tr.pnl), 2) AS total_pnl,
                   ROUND(100.0 * SUM(CASE WHEN tr.pnl > 0 THEN 1 ELSE 0 END) / COUNT(DISTINCT t1.trade_id), 1) AS win_rate
            FROM trade_tags t1
            JOIN trade_tags t2 ON t1.trade_id = t2.trade_id
                              AND (t1.group_id < t2.group_id
                                   OR (t1.group_id = t2.group_id AND t1.tag < t2.tag))
            JOIN trades tr ON tr.id = t1.trade_id
            JOIN trading_days d ON d.id = tr.day_id
            WHERE 1=1 {p_filter_tag}
            GROUP BY t1.group_id, t1.tag, t2.group_id, t2.tag
            HAVING COUNT(DISTINCT t1.trade_id) >= 3
            ORDER BY win_rate DESC
        """, date_params).fetchall()

        correlations = []
        for r in rows:
            rd = dict(r)
            rd["lift"] = round(rd["win_rate"] - overall_wr, 1)
            correlations.append(rd)

        # Sort by absolute lift (biggest impact first), take top 15
        correlations.sort(key=lambda x: abs(x["lift"]), reverse=True)
        return correlations[:15]
    except Exception:
        return []


def _compute_drawdown(equity_curve):
    """Compute drawdown series and max drawdown from equity curve."""
    if not equity_curve:
        return {"max_dd": 0, "max_dd_pct": 0, "series": [], "max_dd_start": None, "max_dd_end": None}

    peak = 0
    max_dd = 0
    max_dd_pct = 0
    dd_series = []
    max_dd_start_idx = 0
    max_dd_end_idx = 0
    peak_idx = 0

    for i, point in enumerate(equity_curve):
        cum = point["cumulative"]
        if cum > peak:
            peak = cum
            peak_idx = i
        dd = peak - cum  # drawdown in dollars (always >= 0)
        dd_pct = (dd / peak * 100) if peak > 0 else 0
        dd_series.append({
            "date": point["date"],
            "time": point["time"],
            "drawdown": round(dd, 2),
            "drawdown_pct": round(dd_pct, 1),
        })
        if dd > max_dd:
            max_dd = round(dd, 2)
            max_dd_pct = round(dd_pct, 1)
            max_dd_start_idx = peak_idx
            max_dd_end_idx = i

    return {
        "max_dd": max_dd,
        "max_dd_pct": max_dd_pct,
        "series": dd_series,
        "max_dd_start": equity_curve[max_dd_start_idx]["date"] if equity_curve else None,
        "max_dd_end": equity_curve[max_dd_end_idx]["date"] if equity_curve else None,
    }


def _compute_duration_stats(trades):
    """Compute trade duration in minutes from entry_time to exit_time."""
    durations = []
    for t in trades:
        try:
            entry = t["entry_time"].strip()
            exit_ = t["exit_time"].strip()
            # Handle HH:MM or HH:MM:SS
            efmt = "%H:%M:%S" if len(entry) > 5 else "%H:%M"
            xfmt = "%H:%M:%S" if len(exit_) > 5 else "%H:%M"
            from datetime import datetime as _dt
            e = _dt.strptime(entry, efmt)
            x = _dt.strptime(exit_, xfmt)
            mins = (x - e).total_seconds() / 60
            if mins < 0:
                mins += 24 * 60  # overnight
            durations.append({
                "duration_mins": round(mins, 1),
                "pnl": t["pnl"],
                "direction": t["direction"],
                "date": t["date"],
            })
        except (ValueError, AttributeError):
            continue

    # Average duration
    avg_dur = round(sum(d["duration_mins"] for d in durations) / len(durations), 1) if durations else 0

    return {
        "trades": durations,
        "avg_duration": avg_dur,
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

def create_live_trade(account_id, direction, instrument, entry_price, entry_time,
                      total_qty, mode, notes="", tags_json="{}",
                      notes_monitoring="", notes_exit=""):
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO live_trades
                (account_id, direction, instrument, entry_price, entry_time,
                 total_qty, mode, notes, tags_json, notes_monitoring, notes_exit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (account_id, direction, instrument, entry_price, entry_time,
              total_qty, mode, notes, tags_json, notes_monitoring, notes_exit))
        return cur.lastrowid


def get_live_trade(live_trade_id):
    with get_conn() as conn:
        row = conn.execute("""
            SELECT lt.*, a.name as account_name, a.color as account_color
            FROM live_trades lt
            LEFT JOIN accounts a ON a.id = lt.account_id
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
            SELECT lt.*, a.name as account_name, a.color as account_color
            FROM live_trades lt
            LEFT JOIN accounts a ON a.id = lt.account_id
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


# ── Shadow Trades ────────────────────────────────────────────────────────────

def upsert_shadow_trade(source_trade_id, account_id, projected_qty, projected_instrument, projected_pnl):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO shadow_trades (source_trade_id, account_id, projected_qty, projected_instrument, projected_pnl)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_trade_id, account_id) DO UPDATE SET
                projected_qty = excluded.projected_qty,
                projected_instrument = excluded.projected_instrument,
                projected_pnl = excluded.projected_pnl
        """, (source_trade_id, account_id, projected_qty, projected_instrument, round(projected_pnl, 2)))


def get_shadows_for_trade(source_trade_id):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT s.*, a.name as account_name, a.color as account_color,
                   a.account_size
            FROM shadow_trades s
            JOIN accounts a ON a.id = s.account_id
            WHERE s.source_trade_id = ?
        """, (source_trade_id,)).fetchall()
        return [dict(r) for r in rows]


def get_shadows_for_account(account_id):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT s.*, t.direction, t.avg_entry, t.avg_exit, t.entry_time, t.exit_time,
                   t.notes, t.notes_monitoring, t.notes_exit,
                   d.date, d.account_id as source_account_id
            FROM shadow_trades s
            JOIN trades t ON t.id = s.source_trade_id
            JOIN trading_days d ON d.id = t.day_id
            WHERE s.account_id = ?
            ORDER BY d.date, t.entry_time
        """, (account_id,)).fetchall()
        return [dict(r) for r in rows]


def delete_shadows_for_trade(source_trade_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM shadow_trades WHERE source_trade_id = ?", (source_trade_id,))


def get_primary_account():
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE is_primary = 1").fetchone()
        return dict(row) if row else None


def get_all_account_summaries():
    """Get summary stats for each account including shadow trade data."""
    with get_conn() as conn:
        accounts = conn.execute("SELECT * FROM accounts ORDER BY is_primary DESC, name").fetchall()
        summaries = []
        for p in accounts:
            p = dict(p)
            pid = p["id"]

            if p["is_primary"]:
                # Real trades
                stats = conn.execute("""
                    SELECT COUNT(t.id) as trade_count,
                           ROUND(COALESCE(SUM(t.pnl), 0), 2) as total_pnl,
                           SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as wins
                    FROM trades t
                    JOIN trading_days d ON d.id = t.day_id
                    WHERE d.account_id = ?
                """, (pid,)).fetchone()
            else:
                # Shadow trades
                stats = conn.execute("""
                    SELECT COUNT(s.id) as trade_count,
                           ROUND(COALESCE(SUM(s.projected_pnl), 0), 2) as total_pnl,
                           SUM(CASE WHEN s.projected_pnl > 0 THEN 1 ELSE 0 END) as wins
                    FROM shadow_trades s
                    WHERE s.account_id = ?
                """, (pid,)).fetchone()

            stats = dict(stats) if stats else {"trade_count": 0, "total_pnl": 0, "wins": 0}
            p["trade_count"] = stats["trade_count"] or 0
            p["total_pnl"] = stats["total_pnl"] or 0
            p["wins"] = stats["wins"] or 0
            p["win_rate"] = round(p["wins"] / p["trade_count"] * 100, 1) if p["trade_count"] else 0

            # Equity for the account
            account_size = p.get("account_size") or 0
            p["equity"] = round(account_size + p["total_pnl"], 2)
            p["equity_pct"] = round(p["total_pnl"] / account_size * 100, 1) if account_size else 0

            summaries.append(p)
        return summaries


def get_shadow_equity_curve(account_id):
    """Get equity curve for a shadow account based on shadow trades."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT d.date, t.entry_time as time, s.projected_pnl as pnl
            FROM shadow_trades s
            JOIN trades t ON t.id = s.source_trade_id
            JOIN trading_days d ON d.id = t.day_id
            WHERE s.account_id = ?
            ORDER BY d.date, t.entry_time
        """, (account_id,)).fetchall()

        curve = []
        cumulative = 0
        for r in rows:
            cumulative = round(cumulative + r["pnl"], 2)
            curve.append({
                "date": r["date"],
                "time": r["time"],
                "pnl": round(r["pnl"], 2),
                "cumulative": cumulative,
            })
        return curve


def get_cross_account_trades(limit=50):
    """Get recent trades with P&L across all accounts (primary + shadows)."""
    with get_conn() as conn:
        # Get primary account trades
        primary = get_primary_account()
        if not primary:
            return []

        trades = conn.execute("""
            SELECT t.id, t.direction, t.avg_entry, t.avg_exit, t.entry_time, t.exit_time,
                   t.pnl, t.qty, d.date
            FROM trades t
            JOIN trading_days d ON d.id = t.day_id
            WHERE d.account_id = ?
            ORDER BY d.date DESC, t.entry_time DESC
            LIMIT ?
        """, (primary["id"], limit)).fetchall()

        # Get all accounts
        all_accts = conn.execute("SELECT id, name, color, is_primary, default_qty, default_instrument FROM accounts ORDER BY is_primary DESC, name").fetchall()

        result = []
        for t in trades:
            t = dict(t)
            # Get shadow P&Ls for this trade
            shadows = conn.execute("""
                SELECT s.account_id, s.projected_qty, s.projected_instrument, s.projected_pnl
                FROM shadow_trades s WHERE s.source_trade_id = ?
            """, (t["id"],)).fetchall()
            shadow_map = {s["account_id"]: dict(s) for s in shadows}

            t["accounts"] = []
            for a in all_accts:
                a = dict(a)
                if a["is_primary"]:
                    t["accounts"].append({
                        "account_id": a["id"], "name": a["name"], "color": a["color"],
                        "qty": t["qty"], "instrument": "MES", "pnl": t["pnl"],
                    })
                elif a["id"] in shadow_map:
                    s = shadow_map[a["id"]]
                    t["accounts"].append({
                        "account_id": a["id"], "name": a["name"], "color": a["color"],
                        "qty": s["projected_qty"], "instrument": s["projected_instrument"],
                        "pnl": s["projected_pnl"],
                    })
            result.append(t)
        return result
