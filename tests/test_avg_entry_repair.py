"""avg_entry must be the qty-weighted average across every entry fill.

A multi-entry trade used to land in the journal carrying only its OPEN price,
because live_trades.weighted_avg_entry collapses to 0 once the trade is fully
closed and a migration then reset the zero back to entry_price. The stored pnl
was always computed from the true weighted entry, so the row contradicted
itself. These tests pin the push path and the one-shot repair.
"""
import json

import app_logic as logic
import database as db


def _entry_fill_weighted(trade_id):
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT f.qty, f.price FROM fills f JOIN trades t ON t.id = f.trade_id "
            "WHERE f.trade_id = ? AND ((t.direction='Long' AND f.side='Buy') "
            "OR (t.direction='Short' AND f.side='Sell'))", (trade_id,)
        ).fetchall()
    return sum(r["qty"] * r["price"] for r in rows) / sum(r["qty"] for r in rows)


def _avg_entry(trade_id):
    with db.get_conn() as conn:
        return conn.execute("SELECT avg_entry FROM trades WHERE id = ?",
                            (trade_id,)).fetchone()["avg_entry"]


def test_push_stores_the_weighted_entry_not_the_open_price(tmp_db):
    """The reported case: open 3 @ 7756, add 3 @ 7766 -> 7761, never 7756."""
    live_id = db.create_live_trade(None, "Long", "MES", 7756.0, "10:05", 3, "full")
    db.add_live_trade_execution(live_id, "OPEN", 1, 3, 7756.0, "10:05", 0.0)
    db.add_live_trade_execution(live_id, "ADD", 1, 3, 7766.0, "10:05", 0.0)
    db.add_live_trade_execution(live_id, "EXIT", 1, 3, 7786.0, "10:30", 375.0)
    db.add_live_trade_execution(live_id, "EXIT", 1, 3, 7805.0, "10:40", 660.0)

    trade_id = logic.close_live_trade_to_journal(live_id)

    assert _avg_entry(trade_id) == 7761.0


def test_push_weighted_entry_is_direction_agnostic(tmp_db):
    live_id = db.create_live_trade(None, "Short", "MES", 7800.0, "10:05", 2, "full")
    db.add_live_trade_execution(live_id, "OPEN", 1, 2, 7800.0, "10:05", 0.0)
    db.add_live_trade_execution(live_id, "ADD", 1, 6, 7820.0, "10:10", 0.0)
    db.add_live_trade_execution(live_id, "EXIT", 1, 8, 7790.0, "10:40", 0.0)

    trade_id = logic.close_live_trade_to_journal(live_id)

    assert _avg_entry(trade_id) == 7815.0   # (7800*2 + 7820*6) / 8


def test_single_entry_trade_is_unchanged_by_the_weighting(tmp_db):
    live_id = db.create_live_trade(None, "Long", "MES", 7715.0, "10:05", 3, "full")
    db.add_live_trade_execution(live_id, "OPEN", 1, 3, 7715.0, "10:05", 0.0)
    db.add_live_trade_execution(live_id, "EXIT", 1, 3, 7724.5, "10:20", 142.5)

    trade_id = logic.close_live_trade_to_journal(live_id)

    assert _avg_entry(trade_id) == 7715.0


def test_repair_corrects_a_trade_whose_avg_entry_disagrees_with_its_fills(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 6, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40",
                               execution_json=json.dumps({"instrument": "MES"}))
    db.insert_fill(trade_id, "10:05", "Buy", 3, 7756.0)
    db.insert_fill(trade_id, "10:05", "Buy", 3, 7766.0)
    db.insert_fill(trade_id, "10:40", "Sell", 6, 7795.5, exit_type="manual_exit")
    assert _avg_entry(trade_id) == 7756.0

    db.repair_avg_entry_from_fills()

    assert _avg_entry(trade_id) == 7761.0
    assert _avg_entry(trade_id) == _entry_fill_weighted(trade_id)


def test_repair_leaves_a_correct_trade_alone_and_is_idempotent(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7715.0, 7724.5, 142.5,
                               "10:05", "10:20")
    db.insert_fill(trade_id, "10:05", "Buy", 3, 7715.0)
    db.insert_fill(trade_id, "10:20", "Sell", 3, 7724.5, exit_type="manual_exit")

    db.repair_avg_entry_from_fills()
    db.repair_avg_entry_from_fills()

    assert _avg_entry(trade_id) == 7715.0


def test_repair_ignores_trades_that_have_no_entry_fills(tmp_db, day_id):
    """Imported trades may carry no fills; their avg_entry must not be zeroed."""
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7715.0, 7724.5, 142.5,
                               "10:05", "10:20")

    db.repair_avg_entry_from_fills()

    assert _avg_entry(trade_id) == 7715.0
