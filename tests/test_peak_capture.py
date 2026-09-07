import json

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

    rows = db.get_trades_missing_mfe_for_date(None, "2026-09-01")
    ids = [r["id"] for r in rows]
    assert missing in ids
    assert filled not in ids


def test_get_trades_missing_mfe_for_date_is_never_capped(tmp_db, day_id):
    """Today's trades are the point of the strip and must never be capped
    away, unlike the earlier-days backfill."""
    ids = [_trade(day_id, num=n) for n in range(1, 13)]
    rows = db.get_trades_missing_mfe_for_date(None, "2026-09-01")
    assert {r["id"] for r in rows} == set(ids)
    assert len(rows) == 12


def test_get_trades_missing_mfe_before_is_capped_tightly(tmp_db):
    for n in range(1, 13):
        day = db.upsert_day(f"2026-08-{n:02d}", None)
        _trade(day, num=1)

    rows = db.get_trades_missing_mfe_before(None, "2026-09-01", limit=10)
    assert len(rows) == 10


def test_count_trades_missing_mfe_reports_the_true_total(tmp_db):
    """The header must read this count, not the length of a capped list."""
    for n in range(1, 13):
        day = db.upsert_day(f"2026-08-{n:02d}", None)
        _trade(day, num=1)
    today = db.upsert_day("2026-09-01", None)
    _trade(today, num=1)

    assert db.count_trades_missing_mfe(None, "2026-09-01") == 13
    # earlier query alone is capped, so it must not equal the true count
    assert len(db.get_trades_missing_mfe_before(None, "2026-09-01", limit=10)) == 10


def test_missing_mfe_account_scoping_excludes_other_accounts(tmp_db):
    """A day with account_id=None must show only NULL-account trades, not
    every account's trades — the pre-fix bug widened to 'all' whenever the
    caller's account_id was falsy."""
    acct_id = db.create_account("Sim", "#fff")
    day_no_acct = db.upsert_day("2026-09-01", None)
    _trade(day_no_acct, num=1)

    # Same date, but a different (real) account — must not leak in.
    day_with_acct = db.upsert_day("2026-09-01", acct_id)
    _trade(day_with_acct, num=1)

    rows = db.get_trades_missing_mfe_for_date(None, "2026-09-01")
    assert len(rows) == 1

    rows_for_acct = db.get_trades_missing_mfe_for_date(acct_id, "2026-09-01")
    assert len(rows_for_acct) == 1


def _seed(day_id, num, target=None):
    trade_id = db.insert_trade(day_id, num, "Long", 3, 7715.0, 7731.25, 240.0,
                               "17:32", "18:02",
                               execution_json=json.dumps({"instrument": "MES"}))
    db.insert_fill(trade_id, "17:32", "Buy", 3, 7715.0,
                   stop_price=7688.5, stop_source="entered",
                   target_price=target,
                   target_source="none" if target is None else "entered")
    db.insert_fill(trade_id, "18:02", "Sell", 3, 7731.25, exit_type="manual_exit")
    return trade_id


def test_plan_check_splits_today_from_earlier_days(tmp_db):
    today = db.upsert_day("2026-09-02", None)
    yesterday = db.upsert_day("2026-09-01", None)
    t_today = _seed(today, 1, target=7760.0)
    t_earlier = _seed(yesterday, 1, target=7760.0)

    result = logic.build_plan_check("2026-09-02", None)

    assert [r["id"] for r in result["today"]] == [t_today]
    assert [r["id"] for r in result["earlier"]] == [t_earlier]


def test_plan_check_shows_the_weighted_target(tmp_db):
    day = db.upsert_day("2026-09-02", None)
    _seed(day, 1, target=7760.0)
    row = logic.build_plan_check("2026-09-02", None)["today"][0]
    assert row["target"] == 7760.0


def test_plan_check_includes_trades_with_no_target(tmp_db):
    """Losers and unplanned trades still need a peak — give-back is invisible
    in P&L."""
    day = db.upsert_day("2026-09-02", None)
    _seed(day, 1, target=None)
    result = logic.build_plan_check("2026-09-02", None)
    assert len(result["today"]) == 1
    assert result["today"][0]["target"] is None


def test_plan_check_drops_a_trade_once_its_peak_is_recorded(tmp_db):
    day = db.upsert_day("2026-09-02", None)
    tid = _seed(day, 1, target=7760.0)
    assert len(logic.build_plan_check("2026-09-02", None)["today"]) == 1
    db.set_trade_mfe(tid, 7772.0, "during", 30)
    assert logic.build_plan_check("2026-09-02", None)["today"] == []


def test_plan_check_reports_the_window(tmp_db):
    db.upsert_day("2026-09-02", None)
    assert logic.build_plan_check("2026-09-02", None)["window_minutes"] == 30


def test_plan_check_caps_earlier_but_never_today(tmp_db):
    """236 closed trades all missing a peak was the real-DB shape that flooded
    every day page under the old LIMIT 50. Today's trades must all render;
    the earlier-days backfill is capped to 10."""
    today = db.upsert_day("2026-09-02", None)
    for n in range(1, 16):
        _seed(today, n, target=7760.0)
    for d in range(1, 21):
        day = db.upsert_day(f"2026-08-{d:02d}", None)
        _seed(day, 1, target=7760.0)

    result = logic.build_plan_check("2026-09-02", None)

    assert len(result["today"]) == 15, "today's trades must never be capped away"
    assert len(result["earlier"]) == 10, "earlier days are capped tightly"


def test_plan_check_reports_the_true_total_and_earlier_total(tmp_db):
    """The header must show the TRUE outstanding count (35), not the length
    of the rendered/capped lists (15 + 10 = 25)."""
    today = db.upsert_day("2026-09-02", None)
    for n in range(1, 16):
        _seed(today, n, target=7760.0)
    for d in range(1, 21):
        day = db.upsert_day(f"2026-08-{d:02d}", None)
        _seed(day, 1, target=7760.0)

    result = logic.build_plan_check("2026-09-02", None)

    assert result["total_missing"] == 35
    assert result["earlier_total"] == 20, (
        "earlier_total is the TRUE earlier-days count (20), not the capped "
        "rendered length (10)"
    )
    assert len(result["earlier"]) == 10


def test_plan_check_scopes_to_the_days_own_account(tmp_db):
    """A legacy NULL-account day must list only NULL-account trades, not
    trades belonging to other accounts."""
    acct_id = db.create_account("Sim", "#fff")
    no_acct_day = db.upsert_day("2026-09-02", None)
    other_acct_day = db.upsert_day("2026-09-02", acct_id)
    _seed(no_acct_day, 1, target=7760.0)
    _seed(other_acct_day, 1, target=7760.0)

    result = logic.build_plan_check("2026-09-02", None)
    assert len(result["today"]) == 1
    assert result["total_missing"] == 1


def test_plan_check_rows_carry_the_weighted_stop(tmp_db):
    """The strip shows stop | entry | plan | exit, so the row needs the stop."""
    day = db.upsert_day("2026-09-02", None)
    trade_id = db.insert_trade(day, 1, "Long", 6, 7761.0, 7795.5, 1035.0,
                               "10:05", "10:40")
    db.insert_fill(trade_id, "10:05", "Buy", 3, 7756.0, stop_price=7736.0,
                   stop_source="entered", target_price=7786.0, target_source="entered")
    db.insert_fill(trade_id, "10:05", "Buy", 3, 7766.0, stop_price=7746.0,
                   stop_source="entered", target_price=7815.0, target_source="entered")
    db.insert_fill(trade_id, "10:40", "Sell", 6, 7795.5, exit_type="manual_exit")

    row = logic.build_plan_check("2026-09-02", None)["today"][0]

    assert row["stop"] == 7741.0
    assert row["target"] == 7800.5
    assert row["avg_entry"] == 7761.0
