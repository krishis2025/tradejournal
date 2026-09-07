import os

import app_logic as logic
import database as db


def test_harness_uses_a_throwaway_db(tmp_db):
    """The schema is built in the temp file, and it is not the repo's journal."""
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


def test_target_columns_exist_on_both_ledgers(tmp_db):
    with db.get_conn() as conn:
        fill_cols = [r[1] for r in conn.execute("PRAGMA table_info(fills)").fetchall()]
        lte_cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(live_trade_executions)").fetchall()]
    for cols in (fill_cols, lte_cols):
        assert "target_price" in cols
        assert "target_source" in cols


def test_target_migration_is_rerunnable(tmp_db):
    db.init_db()
    db.init_db()
    with db.get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(fills)").fetchall()]
    assert cols.count("target_price") == 1
    assert cols.count("target_source") == 1


def test_target_defaults_to_none_source_and_null_price(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7715.0, 7731.0, 240.0,
                               "17:32", "18:02")
    db.insert_fill(trade_id, "17:32", "Buy", 3, 7715.0)
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT target_price, target_source FROM fills WHERE trade_id = ?",
            (trade_id,)).fetchone()
    assert row["target_price"] is None
    assert row["target_source"] == "none"


def test_insert_fill_stores_an_entered_target(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7715.0, 7731.0, 240.0,
                               "17:32", "18:02")
    db.insert_fill(trade_id, "17:32", "Buy", 3, 7715.0,
                   stop_price=7688.5, stop_source="entered",
                   target_price=7760.0, target_source="entered")
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT target_price, target_source FROM fills WHERE trade_id = ?",
            (trade_id,)).fetchone()
    assert row["target_price"] == 7760.0
    assert row["target_source"] == "entered"


def test_update_live_trade_execution_target_sets_edited(tmp_db):
    live_id = db.create_live_trade(None, "Long", "MES", 7715.0, "17:32", 3, "full")
    exec_id = db.add_live_trade_execution(live_id, "OPEN", 1, 3, 7715.0, "17:32", 0.0)
    db.update_live_trade_execution_target(exec_id, live_id, 7770.0)
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT target_price, target_source FROM live_trade_executions WHERE id = ?",
            (exec_id,)).fetchone()
    assert row["target_price"] == 7770.0
    assert row["target_source"] == "edited"


def test_live_trade_has_exit_ignores_case_of_exec_type(tmp_db):
    """exec_type is mixed case in real data: OPEN/ADD/EXIT but also tp_hit,
    stop_hit, manual_exit. Anything that is not OPEN/ADD is an exit."""
    live_id = db.create_live_trade(None, "Long", "MES", 7715.0, "17:32", 3, "full")
    db.add_live_trade_execution(live_id, "OPEN", 1, 3, 7715.0, "17:32", 0.0)
    assert db.live_trade_has_exit(live_id) is False

    db.add_live_trade_execution(live_id, "ADD", 1, 2, 7720.0, "17:40", 0.0)
    assert db.live_trade_has_exit(live_id) is False

    db.add_live_trade_execution(live_id, "manual_exit", 1, 5, 7731.0, "18:02", 240.0)
    assert db.live_trade_has_exit(live_id) is True


def test_create_live_trade_stores_entered_target(client, tmp_db):
    res = client.post("/api/live", json={
        "direction": "Long", "instrument": "MES", "entry_price": 7715.0,
        "total_qty": 3, "entry_time": "17:32", "mode": "full",
        "stop_price": 7688.5, "target_price": 7760.0,
    })
    assert res.status_code == 200
    live_id = res.get_json()["id"]
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT target_price, target_source FROM live_trade_executions "
            "WHERE live_trade_id = ? AND exec_type = 'OPEN'", (live_id,)).fetchone()
    assert row["target_price"] == 7760.0
    assert row["target_source"] == "entered"


def test_create_live_trade_without_target_stores_none(client, tmp_db):
    res = client.post("/api/live", json={
        "direction": "Long", "instrument": "MES", "entry_price": 7715.0,
        "total_qty": 3, "entry_time": "17:32", "mode": "full",
    })
    live_id = res.get_json()["id"]
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT target_price, target_source FROM live_trade_executions "
            "WHERE live_trade_id = ? AND exec_type = 'OPEN'", (live_id,)).fetchone()
    assert row["target_price"] is None
    assert row["target_source"] == "none"


def test_patch_target_before_any_exit_succeeds(client, tmp_db):
    live_id = client.post("/api/live", json={
        "direction": "Long", "instrument": "MES", "entry_price": 7715.0,
        "total_qty": 3, "entry_time": "17:32", "mode": "full",
    }).get_json()["id"]
    with db.get_conn() as conn:
        exec_id = conn.execute(
            "SELECT id FROM live_trade_executions WHERE live_trade_id = ?",
            (live_id,)).fetchone()["id"]

    res = client.patch(f"/api/live/{live_id}/execution/{exec_id}/target",
                       json={"target_price": 7770.0})
    assert res.status_code == 200
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT target_price, target_source FROM live_trade_executions WHERE id = ?",
            (exec_id,)).fetchone()
    assert row["target_price"] == 7770.0
    assert row["target_source"] == "edited"


def test_patch_target_after_an_exit_returns_409_and_changes_nothing(client, tmp_db):
    """The freeze. Enforced server-side so a stale tab cannot slip past the UI lock."""
    live_id = client.post("/api/live", json={
        "direction": "Long", "instrument": "MES", "entry_price": 7715.0,
        "total_qty": 3, "entry_time": "17:32", "mode": "full", "target_price": 7760.0,
    }).get_json()["id"]
    with db.get_conn() as conn:
        exec_id = conn.execute(
            "SELECT id FROM live_trade_executions WHERE live_trade_id = ?",
            (live_id,)).fetchone()["id"]

    db.add_live_trade_execution(live_id, "manual_exit", 1, 3, 7731.0, "18:02", 240.0)

    res = client.patch(f"/api/live/{live_id}/execution/{exec_id}/target",
                       json={"target_price": 7999.0})
    assert res.status_code == 409
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT target_price FROM live_trade_executions WHERE id = ?",
            (exec_id,)).fetchone()
    assert row["target_price"] == 7760.0


def test_patch_target_with_mismatched_live_id_does_not_modify_the_row(client, tmp_db):
    """The freeze guard checks live_trade_has_exit(live_id); the write must be
    scoped to that same live_id or a request naming an unrelated (already-
    exited) trade's exec_id, routed through a different still-open live_id,
    could rewrite a row the guard was supposed to protect."""
    exited_live_id = client.post("/api/live", json={
        "direction": "Long", "instrument": "MES", "entry_price": 7715.0,
        "total_qty": 3, "entry_time": "17:32", "mode": "full", "target_price": 7760.0,
    }).get_json()["id"]
    with db.get_conn() as conn:
        exited_exec_id = conn.execute(
            "SELECT id FROM live_trade_executions WHERE live_trade_id = ?",
            (exited_live_id,)).fetchone()["id"]
    db.add_live_trade_execution(exited_live_id, "manual_exit", 1, 3, 7731.0, "18:02", 240.0)

    other_live_id = client.post("/api/live", json={
        "direction": "Long", "instrument": "MES", "entry_price": 7700.0,
        "total_qty": 2, "entry_time": "17:00", "mode": "full",
    }).get_json()["id"]

    # PATCH names the still-open trade's live_id but the exited trade's exec_id.
    res = client.patch(
        f"/api/live/{other_live_id}/execution/{exited_exec_id}/target",
        json={"target_price": 9999.0})
    assert res.status_code == 200  # guard passes: other_live_id has no exit

    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT target_price FROM live_trade_executions WHERE id = ?",
            (exited_exec_id,)).fetchone()
    assert row["target_price"] == 7760.0, "mismatched live_id must not modify the row"


def test_patch_target_rejects_missing_price(client, tmp_db):
    live_id = client.post("/api/live", json={
        "direction": "Long", "instrument": "MES", "entry_price": 7715.0,
        "total_qty": 3, "entry_time": "17:32", "mode": "full",
    }).get_json()["id"]
    with db.get_conn() as conn:
        exec_id = conn.execute(
            "SELECT id FROM live_trade_executions WHERE live_trade_id = ?",
            (live_id,)).fetchone()["id"]
    res = client.patch(f"/api/live/{live_id}/execution/{exec_id}/target", json={})
    assert res.status_code == 400


def test_push_to_journal_carries_target_onto_entry_fills_only(client, tmp_db):
    live_id = client.post("/api/live", json={
        "direction": "Long", "instrument": "MES", "entry_price": 7715.0,
        "total_qty": 3, "entry_time": "17:32", "mode": "full",
        "stop_price": 7688.5, "target_price": 7760.0,
    }).get_json()["id"]
    db.add_live_trade_execution(live_id, "manual_exit", 1, 3, 7731.0, "18:02", 240.0)

    trade_id = logic.close_live_trade_to_journal(live_id)

    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT side, target_price, target_source FROM fills WHERE trade_id = ? "
            "ORDER BY side", (trade_id,)).fetchall()

    entry = [r for r in rows if r["side"] == "Buy"]
    exits = [r for r in rows if r["side"] == "Sell"]
    assert entry and exits
    assert entry[0]["target_price"] == 7760.0
    assert entry[0]["target_source"] == "entered"
    for r in exits:
        assert r["target_price"] is None
        assert r["target_source"] == "none"
