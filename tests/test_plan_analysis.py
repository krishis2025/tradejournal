import json

import database as db
import app_logic as logic


# ── weighted_plan_price ──────────────────────────────────────────────────────

def test_weighted_plan_price_weights_by_qty():
    fills = [{"qty": 3, "target_price": 7760.0}, {"qty": 2, "target_price": 7770.0}]
    assert logic.weighted_plan_price(fills, "target_price") == 7764.0


def test_weighted_plan_price_ignores_rows_without_a_value():
    """A trade targeted on the core but not the add still yields an honest number."""
    fills = [{"qty": 3, "target_price": 7760.0}, {"qty": 2, "target_price": None}]
    assert logic.weighted_plan_price(fills, "target_price") == 7760.0


def test_weighted_plan_price_is_none_when_nothing_is_set():
    fills = [{"qty": 3, "target_price": None}, {"qty": 2, "target_price": None}]
    assert logic.weighted_plan_price(fills, "target_price") is None


def test_weighted_plan_price_handles_an_empty_list():
    assert logic.weighted_plan_price([], "target_price") is None


# ── compute_capture ──────────────────────────────────────────────────────────

def test_capture_on_a_long_cut_short():
    # planned 45 pts (7715 -> 7760), captured 16.25
    c = logic.compute_capture("Long", 7715.0, 7731.25, 7760.0)
    assert round(c, 4) == 0.3611


def test_capture_is_symmetric_for_shorts():
    c = logic.compute_capture("Short", 7760.0, 7743.75, 7715.0)
    assert round(c, 4) == 0.3611


def test_capture_is_one_when_the_exit_lands_on_the_plan():
    assert logic.compute_capture("Long", 7715.0, 7760.0, 7760.0) == 1.0


def test_capture_exceeds_one_when_held_past_the_plan():
    c = logic.compute_capture("Long", 7715.0, 7770.0, 7760.0)
    assert c > 1.0


def test_capture_is_negative_on_a_loss():
    c = logic.compute_capture("Long", 7715.0, 7688.5, 7760.0)
    assert c < 0


def test_capture_is_none_without_a_target():
    assert logic.compute_capture("Long", 7715.0, 7731.0, None) is None


def test_capture_is_none_when_target_is_within_a_tick_of_entry():
    """A target 0.1 points from entry is not a plan; guard the denominator."""
    assert logic.compute_capture("Long", 7715.0, 7731.0, 7715.1) is None


# ── classify_bucket ──────────────────────────────────────────────────────────

def test_bucket_boundaries_with_the_default_bounds():
    """Asymmetric on purpose: cutting at 85% of plan is executing it, while
    running 40% past it is a different behaviour worth flagging."""
    b = (0.60, 1.10)
    assert logic.classify_bucket(None, b) == "no_plan"
    assert logic.classify_bucket(-0.5, b) == "stopped"
    assert logic.classify_bucket(0.0, b) == "stopped"
    assert logic.classify_bucket(0.01, b) == "cut_early"
    assert logic.classify_bucket(0.5999, b) == "cut_early"
    assert logic.classify_bucket(0.60, b) == "at_plan"
    assert logic.classify_bucket(0.873, b) == "at_plan"
    assert logic.classify_bucket(1.00, b) == "at_plan"
    assert logic.classify_bucket(1.10, b) == "at_plan"
    assert logic.classify_bucket(1.1001, b) == "ran_past"


def test_bounds_are_independently_configurable(tmp_db):
    db.set_config("plan_capture_low", "0.40")
    db.set_config("plan_capture_high", "1.50")
    assert logic.get_plan_capture_bounds() == (0.40, 1.50)
    assert logic.classify_bucket(0.45) == "at_plan"
    assert logic.classify_bucket(1.40) == "at_plan"
    assert logic.classify_bucket(1.60) == "ran_past"


def test_bounds_fall_back_when_config_is_junk(tmp_db):
    db.set_config("plan_capture_low", "")
    db.set_config("plan_capture_high", "not a number")
    assert logic.get_plan_capture_bounds() == (0.60, 1.10)


def test_the_reported_trade_reads_as_at_plan_not_bailed_early(tmp_db, day_id):
    """Regression for the real T3: entry 7761 (weighted, not the 7756 OPEN),
    exits 7786 and 7805, targets 7786 and 7815, peak 7809.50 after the exit.
    Capture is 0.873 -- executing the plan, not bailing out of it."""
    tid = _seed_trade(day_id, 1, "Long", 7761.0, 7795.5, 1035.0,
                      [(3, 7756.0, 7736.0, 7786.0), (3, 7766.0, 7746.0, 7815.0)])
    db.set_trade_mfe(tid, 7809.5, "after", 30)

    row = logic.build_plan_execution(
        db.get_trades_in_range(None, "2026-09-01", "2026-09-01"))["rows"][0]

    assert row["target"] == 7800.50
    assert row["stop"] == 7741.00
    assert row["avg_entry"] == 7761.00
    assert round(row["capture"], 3) == 0.873
    assert row["bucket"] == "at_plan"


# ── compute_excursion ────────────────────────────────────────────────────────

def test_excursion_during_is_give_back(tmp_db):
    e = logic.compute_excursion("Long", 3, "MES", 7731.25, 7772.0, "during")
    assert e["kind"] == "give_back"
    assert e["points"] == 40.75
    assert e["dollars"] == 611.25  # 40.75 * 3 * $5


def test_excursion_after_is_missed_run(tmp_db):
    e = logic.compute_excursion("Long", 3, "MES", 7731.25, 7772.0, "after")
    assert e["kind"] == "missed_run"


def test_excursion_is_direction_aware(tmp_db):
    e = logic.compute_excursion("Short", 3, "MES", 7743.75, 7700.0, "during")
    assert e["points"] == 43.75
    assert e["dollars"] == 656.25


def test_excursion_uses_the_instrument_point_value(tmp_db):
    e = logic.compute_excursion("Long", 1, "ES", 7731.0, 7741.0, "after")
    assert e["dollars"] == 500.0  # 10 pts * 1 * $50


def test_excursion_is_none_without_a_peak(tmp_db):
    assert logic.compute_excursion("Long", 3, "MES", 7731.0, None, None) is None


# ── db.get_entry_fills_for_trades ────────────────────────────────────────────

def _seed_trade(day_id, num, direction, entry, exit_, pnl, entry_fills, instrument="MES"):
    """Insert one journal trade plus its entry and exit fills."""
    qty = sum(f[0] for f in entry_fills)
    trade_id = db.insert_trade(day_id, num, direction, qty, entry, exit_, pnl,
                               "17:32", "18:02",
                               execution_json=json.dumps({"instrument": instrument}))
    entry_side = "Buy" if direction == "Long" else "Sell"
    exit_side = "Sell" if direction == "Long" else "Buy"
    for q, price, stop, target in entry_fills:
        db.insert_fill(trade_id, "17:32", entry_side, q, price,
                       stop_price=stop, stop_source="entered",
                       target_price=target,
                       target_source="none" if target is None else "entered")
    db.insert_fill(trade_id, "18:02", exit_side, qty, exit_, exit_type="manual_exit")
    return trade_id


def test_get_entry_fills_returns_only_entry_side_rows(tmp_db, day_id):
    long_id = _seed_trade(day_id, 1, "Long", 7715.0, 7731.25, 240.0,
                          [(3, 7715.0, 7688.5, 7760.0)])
    short_id = _seed_trade(day_id, 2, "Short", 7760.0, 7743.75, 240.0,
                           [(3, 7760.0, 7788.5, 7715.0)])

    got = db.get_entry_fills_for_trades([long_id, short_id])

    assert len(got[long_id]) == 1
    assert got[long_id][0]["price"] == 7715.0
    assert got[long_id][0]["target_price"] == 7760.0
    # the Short trade's entry fill is the Sell, not the Buy
    assert len(got[short_id]) == 1
    assert got[short_id][0]["price"] == 7760.0


def test_get_entry_fills_handles_an_empty_id_list(tmp_db):
    assert db.get_entry_fills_for_trades([]) == {}


# ── build_plan_execution ─────────────────────────────────────────────────────

def _rows_by_num(result):
    return {r["trade_num"]: r for r in result["rows"]}


def test_build_plan_execution_assembles_rows(tmp_db, day_id):
    _seed_trade(day_id, 1, "Long", 7715.0, 7731.25, 240.0,
                [(3, 7715.0, 7688.5, 7760.0)])
    trades = db.get_trades_in_range(None, "2026-09-01", "2026-09-01")

    result = logic.build_plan_execution(trades)
    row = _rows_by_num(result)[1]

    assert row["target"] == 7760.0
    assert row["stop"] == 7688.5
    assert round(row["capture"], 4) == 0.3611
    assert row["bucket"] == "cut_early"
    assert row["excursion"] is None


def test_build_plan_execution_applies_the_peak(tmp_db, day_id):
    tid = _seed_trade(day_id, 1, "Long", 7715.0, 7731.25, 240.0,
                      [(3, 7715.0, 7688.5, 7760.0)])
    db.set_trade_mfe(tid, 7772.0, "during", 30)
    trades = db.get_trades_in_range(None, "2026-09-01", "2026-09-01")

    row = _rows_by_num(logic.build_plan_execution(trades))[1]
    assert row["excursion"]["kind"] == "give_back"
    assert row["excursion"]["dollars"] == 611.25


def test_build_plan_execution_flags_a_partial_plan(tmp_db, day_id):
    _seed_trade(day_id, 1, "Long", 7715.0, 7731.25, 240.0,
                [(3, 7715.0, 7688.5, 7760.0), (2, 7720.0, 7688.5, None)])
    trades = db.get_trades_in_range(None, "2026-09-01", "2026-09-01")
    row = _rows_by_num(logic.build_plan_execution(trades))[1]
    assert row["partial_plan"] is True
    assert row["target"] == 7760.0


def test_build_plan_execution_marks_untargeted_trades_no_plan(tmp_db, day_id):
    _seed_trade(day_id, 1, "Long", 7715.0, 7731.25, 240.0,
                [(3, 7715.0, 7688.5, None)])
    trades = db.get_trades_in_range(None, "2026-09-01", "2026-09-01")
    result = logic.build_plan_execution(trades)
    assert _rows_by_num(result)[1]["bucket"] == "no_plan"
    assert result["summary"]["no_plan"] == 1


def test_summary_reports_coverage_over_all_trades(tmp_db, day_id):
    a = _seed_trade(day_id, 1, "Long", 7715.0, 7731.25, 240.0,
                    [(3, 7715.0, 7688.5, 7760.0)])
    _seed_trade(day_id, 2, "Long", 7715.0, 7731.25, 240.0,
                [(3, 7715.0, 7688.5, 7760.0)])
    db.set_trade_mfe(a, 7772.0, "during", 30)

    summary = logic.build_plan_execution(
        db.get_trades_in_range(None, "2026-09-01", "2026-09-01"))["summary"]

    assert summary["coverage"]["covered"] == 1
    assert summary["coverage"]["total"] == 2


def test_summary_survives_a_week_with_no_trades(tmp_db):
    result = logic.build_plan_execution([])
    assert result["rows"] == []
    assert result["summary"]["coverage"] == {"covered": 0, "total": 0}


def test_exit_tag_vocabulary_covers_the_reasons_the_data_cannot_derive(tmp_db):
    """Retargeted from the TAG_GROUPS constant to get_tag_groups() — every real
    caller reads through get_tag_groups(), which returns a DB tag_config
    override WHOLESALE the moment one exists. A test against the constant
    alone cannot catch a database whose override predates the widened
    vocabulary, which is exactly how F1 survived eleven reviews."""
    group = next(g for g in logic.get_tag_groups() if g["id"] == "exit")
    for tag in ("Target hit", "Target never reached", "Stopped out",
                "Greed / chased", "Time stop", "Management error"):
        assert tag in group["tags"], f"missing exit tag: {tag}"
    # the two originals must survive so existing tagged trades stay valid
    assert "Planned — Monitored Continuation" in group["tags"]
    assert "Fear / Anxious" in group["tags"]
    assert group["multi"] is False


def test_migration_appends_missing_exit_tags_to_a_pre_existing_override(tmp_db):
    """The real database's exit override predates the widened vocabulary:
    ('Planned — Monitored Continuation', 0), ('Fear / Anxious', 1),
    ('Bailed out - Reasses', 2), with 5 trades tagged 'Bailed out - Reasses'
    (the real-DB shape). The migration must append the six new tags after
    position 2 without touching the three existing rows or any trade_tags —
    reordering or renumbering would make save_tag_config's position-based
    rename cascade silently relabel those 5 real trades."""
    with db.get_conn() as conn:
        conn.execute("DELETE FROM tag_config WHERE group_id = 'exit'")
        for pos, tag in enumerate(
            ["Planned — Monitored Continuation", "Fear / Anxious", "Bailed out - Reasses"]
        ):
            conn.execute(
                "INSERT INTO tag_config (group_id, tag, position, enabled) "
                "VALUES ('exit', ?, ?, 1)", (tag, pos)
            )

    day_id = db.upsert_day("2026-09-01", None)
    bailed_trade_ids = []
    for n in range(1, 6):
        trade_id = db.insert_trade(day_id, n, "Long", 3, 7715.0, 7731.0, 240.0,
                                   "17:32", "18:02")
        db.set_trade_tags(trade_id, "exit", ["Bailed out - Reasses"])
        bailed_trade_ids.append(trade_id)

    db.init_db()

    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT tag, position FROM tag_config WHERE group_id = 'exit' ORDER BY position"
        ).fetchall()
    by_tag = {r["tag"]: r["position"] for r in rows}

    # the three pre-existing rows keep their exact original positions
    assert by_tag["Planned — Monitored Continuation"] == 0
    assert by_tag["Fear / Anxious"] == 1
    assert by_tag["Bailed out - Reasses"] == 2

    # the six new tags were appended after the pre-existing maximum
    new_tags = {"Target hit", "Target never reached", "Stopped out",
                "Greed / chased", "Time stop", "Management error"}
    assert new_tags <= set(by_tag)
    assert all(by_tag[t] > 2 for t in new_tags)
    assert len(rows) == 9

    # all 5 trades tagged 'Bailed out - Reasses' are untouched
    with db.get_conn() as conn:
        for tid in bailed_trade_ids:
            tt = conn.execute(
                "SELECT tag FROM trade_tags WHERE trade_id = ? AND group_id = 'exit'",
                (tid,)
            ).fetchall()
            assert [r["tag"] for r in tt] == ["Bailed out - Reasses"]
        total_bailed = conn.execute(
            "SELECT COUNT(*) AS c FROM trade_tags WHERE group_id = 'exit' AND tag = ?",
            ("Bailed out - Reasses",)
        ).fetchone()["c"]
    assert total_bailed == 5


def test_migration_appending_exit_tags_is_idempotent(tmp_db):
    """init_db() runs on every request; running it twice must not duplicate rows."""
    with db.get_conn() as conn:
        conn.execute("DELETE FROM tag_config WHERE group_id = 'exit'")
        for pos, tag in enumerate(
            ["Planned — Monitored Continuation", "Fear / Anxious", "Bailed out - Reasses"]
        ):
            conn.execute(
                "INSERT INTO tag_config (group_id, tag, position, enabled) "
                "VALUES ('exit', ?, ?, 1)", (tag, pos)
            )

    db.init_db()
    with db.get_conn() as conn:
        first_pass = conn.execute(
            "SELECT tag, position FROM tag_config WHERE group_id = 'exit' ORDER BY position"
        ).fetchall()

    db.init_db()
    with db.get_conn() as conn:
        second_pass = conn.execute(
            "SELECT tag, position FROM tag_config WHERE group_id = 'exit' ORDER BY position"
        ).fetchall()

    assert [(r["tag"], r["position"]) for r in first_pass] == \
           [(r["tag"], r["position"]) for r in second_pass]
    tags = [r["tag"] for r in second_pass]
    assert len(tags) == len(set(tags)), "no duplicate tag rows after a second init_db()"


def test_migration_is_a_noop_when_exit_group_has_no_override(tmp_db):
    """get_tag_groups() already falls back to TAG_GROUPS when no override
    exists, so the migration must not fabricate a tag_config row for a group
    that was never customized."""
    with db.get_conn() as conn:
        conn.execute("DELETE FROM tag_config WHERE group_id = 'exit'")
    db.init_db()
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tag_config WHERE group_id = 'exit'"
        ).fetchall()
    assert rows == []


# ── weekly payload wiring ─────────────────────────────────────────────────────

def test_weekly_payload_carries_plan_execution(tmp_db):
    day_id = db.upsert_day("2026-08-31", None)   # a Monday
    tid = _seed_trade(day_id, 1, "Long", 7715.0, 7731.25, 240.0,
                      [(3, 7715.0, 7688.5, 7760.0)])
    db.set_trade_mfe(tid, 7772.0, "during", 30)

    data = logic.build_weekly_review_data(None, "2026-08-31")

    assert "plan_execution" in data
    pe = data["plan_execution"]
    assert pe["summary"]["coverage"] == {"covered": 1, "total": 1}
    assert pe["rows"][0]["excursion"]["kind"] == "give_back"


def test_weekly_payload_plan_execution_is_empty_for_a_quiet_week(tmp_db):
    data = logic.build_weekly_review_data(None, "2026-08-31")
    assert data["plan_execution"]["rows"] == []
    assert data["plan_execution"]["summary"]["graded_of"] == 0
