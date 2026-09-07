import database as db


def test_harness_uses_a_throwaway_db(tmp_db):
    """The schema is built in the temp file, and it is not the repo's journal."""
    import os
    repo_db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "journal.db")
    assert os.path.abspath(tmp_db) != os.path.abspath(repo_db)
    assert os.path.exists(tmp_db)
    with db.get_conn() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    assert "trades" in tables
    assert "fills" in tables
    assert "live_trade_executions" in tables


def test_init_db_is_rerunnable(tmp_db):
    """init_db runs on every request; running it twice must not raise."""
    db.init_db()
    db.init_db()
    with db.get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(fills)").fetchall()]
    assert cols.count("stop_price") == 1
