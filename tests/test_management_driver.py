"""What primarily drove the management decisions: the market, or the P&L.

Market and thesis are one choice because they sit on the same side of the
line this field exists to draw — both are reasons outside the trader's own
money. Splitting them would dilute the signal the question is asking for.

Unlike management_issue and process_violation this field has no cross-field
rule: it is always askable, so there is nothing to gate it against.
"""
import app_logic as logic
import database as db


def _cols(table):
    with db.get_conn() as conn:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _driver(trade_id):
    with db.get_conn() as conn:
        return conn.execute("SELECT management_driver FROM trades WHERE id = ?",
                            (trade_id,)).fetchone()["management_driver"]


def test_vocabulary_is_three_values():
    assert logic.MANAGEMENT_DRIVERS == ("market_thesis", "pnl", "both")


def test_column_exists_on_both_tables(tmp_db):
    for table in ("trades", "live_trades"):
        assert "management_driver" in _cols(table), f"missing from {table}"


def test_migration_is_rerunnable(tmp_db):
    db.init_db()
    db.init_db()
    assert _cols("trades").count("management_driver") == 1


def test_defaults_to_null(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, 50.0,
                               "10:00", "10:30")
    assert _driver(trade_id) is None


def test_insert_trade_accepts_it(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, 50.0,
                               "10:00", "10:30", management_driver="pnl")
    assert _driver(trade_id) == "pnl"


def test_validate_accepts_each_legal_value():
    for value in ("market_thesis", "pnl", "both"):
        cleaned, err = logic.validate_assessment({"management_driver": value})
        assert err is None, f"{value} should be accepted"
        assert cleaned["management_driver"] == value


def test_validate_rejects_a_value_outside_the_vocabulary():
    _, err = logic.validate_assessment({"management_driver": "vibes"})
    assert err is not None and "management_driver" in err


def test_validate_clears_it_on_empty():
    cleaned, err = logic.validate_assessment({"management_driver": ""})
    assert err is None
    assert cleaned["management_driver"] is None


def test_it_has_no_cross_field_rule(tmp_db, day_id):
    """Unlike management_issue and process_violation, it stands alone —
    an A-game trade that followed process can still be P&L-driven."""
    cleaned, err = logic.validate_assessment(
        {"grade": "A", "management": "followed", "management_driver": "pnl"})
    assert err is None
    assert cleaned["management_driver"] == "pnl"


def test_post_assessment_stores_it(client, tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, 50.0,
                               "10:00", "10:30")
    res = client.post(f"/api/trade/{trade_id}/assessment",
                      json={"management_driver": "market_thesis"})
    assert res.status_code == 200
    assert _driver(trade_id) == "market_thesis"


def test_post_assessment_rejects_a_bad_value(client, tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, 50.0,
                               "10:00", "10:30")
    res = client.post(f"/api/trade/{trade_id}/assessment",
                      json={"management_driver": "vibes"})
    assert res.status_code == 400
    assert _driver(trade_id) is None


def test_a_partial_write_leaves_the_other_fields_alone(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, 50.0,
                               "10:00", "10:30", grade="B", emotion="greed")
    db.set_trade_assessment(trade_id, management_driver="both")
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    assert row["management_driver"] == "both"
    assert row["grade"] == "B"
    assert row["emotion"] == "greed"


def test_push_carries_it_to_the_journal(tmp_db):
    live_id = db.create_live_trade(None, "Long", "MES", 7756.0, "10:05", 3, "full")
    db.add_live_trade_execution(live_id, "OPEN", 1, 3, 7756.0, "10:05", 0.0)
    db.add_live_trade_execution(live_id, "EXIT", 1, 3, 7786.0, "10:40", 450.0)
    db.update_live_trade(live_id, management_driver="pnl")

    trade_id = logic.close_live_trade_to_journal(live_id)

    assert _driver(trade_id) == "pnl"
