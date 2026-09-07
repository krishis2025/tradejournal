import database as db
import app_logic as logic


def _trade(day_id, num=1, direction="Long", entry=7715.0, exit_=7731.0, pnl=240.0):
    return db.insert_trade(day_id, num, direction, 3, entry, exit_, pnl, "17:32", "18:02")


def test_mfe_columns_exist(tmp_db):
    with db.get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()]
    assert "mfe_price" in cols
    assert "mfe_timing" in cols
    assert "mfe_window_minutes" in cols


def test_mfe_migration_is_rerunnable(tmp_db):
    db.init_db()
    db.init_db()
    with db.get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()]
    assert cols.count("mfe_price") == 1


def test_no_mfe_source_column(tmp_db):
    """mfe_price IS NULL already means 'not observed'; a source column would be
    redundant state to keep in sync."""
    with db.get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()]
    assert "mfe_source" not in cols


def test_set_trade_mfe_stores_all_three(tmp_db, day_id):
    trade_id = _trade(day_id)
    db.set_trade_mfe(trade_id, 7772.0, "during", 30)
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT mfe_price, mfe_timing, mfe_window_minutes FROM trades WHERE id = ?",
            (trade_id,)).fetchone()
    assert row["mfe_price"] == 7772.0
    assert row["mfe_timing"] == "during"
    assert row["mfe_window_minutes"] == 30


def test_default_mfe_window_is_30(tmp_db):
    assert logic.get_mfe_window_minutes() == 30


def test_mfe_window_reads_from_config(tmp_db):
    db.set_config("mfe_window_minutes", "45")
    assert logic.get_mfe_window_minutes() == 45


def test_mfe_window_falls_back_when_config_is_junk(tmp_db):
    db.set_config("mfe_window_minutes", "not a number")
    assert logic.get_mfe_window_minutes() == 30


def test_post_mfe_stamps_the_window_server_side(client, tmp_db, day_id):
    trade_id = _trade(day_id)
    res = client.post(f"/api/trade/{trade_id}/mfe",
                      json={"mfe_price": 7772.0, "mfe_timing": "after",
                            "mfe_window_minutes": 999})
    assert res.status_code == 200
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT mfe_price, mfe_timing, mfe_window_minutes FROM trades WHERE id = ?",
            (trade_id,)).fetchone()
    assert row["mfe_price"] == 7772.0
    assert row["mfe_timing"] == "after"
    assert row["mfe_window_minutes"] == 30, "client-supplied window must be ignored"


def test_post_mfe_rejects_bad_timing(client, tmp_db, day_id):
    trade_id = _trade(day_id)
    res = client.post(f"/api/trade/{trade_id}/mfe",
                      json={"mfe_price": 7772.0, "mfe_timing": "sometime"})
    assert res.status_code == 400


def test_post_mfe_rejects_missing_price(client, tmp_db, day_id):
    trade_id = _trade(day_id)
    res = client.post(f"/api/trade/{trade_id}/mfe", json={"mfe_timing": "during"})
    assert res.status_code == 400


def test_peak_is_overwritable_unlike_the_target(client, tmp_db, day_id):
    """A peak is a checkable fact about the market, not a record of intent, so
    a wrong value should be fixable. Deliberately unlike the target freeze."""
    trade_id = _trade(day_id)
    client.post(f"/api/trade/{trade_id}/mfe",
                json={"mfe_price": 7772.0, "mfe_timing": "during"})
    res = client.post(f"/api/trade/{trade_id}/mfe",
                      json={"mfe_price": 7780.0, "mfe_timing": "after"})
    assert res.status_code == 200
    with db.get_conn() as conn:
        row = conn.execute("SELECT mfe_price, mfe_timing FROM trades WHERE id = ?",
                           (trade_id,)).fetchone()
    assert row["mfe_price"] == 7780.0
    assert row["mfe_timing"] == "after"


def test_get_trades_missing_mfe_excludes_filled_and_open_trades(tmp_db, day_id):
    filled = _trade(day_id, num=1)
    missing = _trade(day_id, num=2)
    db.set_trade_mfe(filled, 7772.0, "during", 30)

    rows = db.get_trades_missing_mfe(None, "2026-09-01")
    ids = [r["id"] for r in rows]
    assert missing in ids
    assert filled not in ids
