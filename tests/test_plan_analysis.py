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

def test_bucket_boundaries_with_the_default_band():
    b = 0.10
    assert logic.classify_bucket(None, b) == "no_plan"
    assert logic.classify_bucket(-0.5, b) == "stopped"
    assert logic.classify_bucket(0.0, b) == "stopped"
    assert logic.classify_bucket(0.01, b) == "cut_early"
    assert logic.classify_bucket(0.8999, b) == "cut_early"
    assert logic.classify_bucket(0.90, b) == "at_plan"
    assert logic.classify_bucket(1.00, b) == "at_plan"
    assert logic.classify_bucket(1.10, b) == "at_plan"
    assert logic.classify_bucket(1.1001, b) == "ran_past"


def test_band_is_configurable(tmp_db):
    db.set_config("plan_capture_band", "0.25")
    assert logic.get_plan_capture_band() == 0.25
    assert logic.classify_bucket(0.80) == "at_plan"


def test_band_falls_back_when_config_is_junk(tmp_db):
    db.set_config("plan_capture_band", "")
    assert logic.get_plan_capture_band() == 0.10


# ── classify_verdict ─────────────────────────────────────────────────────────

def test_verdict_froze_when_the_target_was_reached_before_the_exit():
    v = logic.classify_verdict("cut_early", "Long", 7760.0, 7772.0, "during")
    assert v == "froze_at_target"


def test_verdict_bailed_when_the_target_was_reached_after_the_exit():
    v = logic.classify_verdict("cut_early", "Long", 7760.0, 7772.0, "after")
    assert v == "bailed_early"


def test_verdict_market_didnt_pay_when_the_peak_never_reached_the_target():
    v = logic.classify_verdict("cut_early", "Long", 7760.0, 7750.0, "after")
    assert v == "market_didnt_pay"


def test_verdict_counts_a_peak_exactly_at_the_target_as_offered():
    v = logic.classify_verdict("cut_early", "Long", 7760.0, 7760.0, "during")
    assert v == "froze_at_target"


def test_verdict_is_direction_aware_for_shorts():
    # short target 7715; a peak of 7700 is BETTER than the target
    assert logic.classify_verdict("cut_early", "Short", 7715.0, 7700.0, "during") == "froze_at_target"
    assert logic.classify_verdict("cut_early", "Short", 7715.0, 7730.0, "during") == "market_didnt_pay"


def test_verdict_is_none_without_a_peak():
    assert logic.classify_verdict("cut_early", "Long", 7760.0, None, None) is None


def test_verdict_only_applies_to_cut_early():
    assert logic.classify_verdict("at_plan", "Long", 7760.0, 7772.0, "during") is None
    assert logic.classify_verdict("ran_past", "Long", 7760.0, 7772.0, "during") is None
    assert logic.classify_verdict("stopped", "Long", 7760.0, 7772.0, "during") is None


# ── exit_tag_signals ─────────────────────────────────────────────────────────

def test_tag_conflict_when_tagged_target_hit_but_peak_never_reached_it():
    sig = logic.exit_tag_signals(["Target hit"], False)
    assert sig["conflict"] is True


def test_tag_conflict_when_tagged_never_reached_but_peak_did_reach_it():
    sig = logic.exit_tag_signals(["Target never reached"], True)
    assert sig["conflict"] is True


def test_no_tag_conflict_when_tag_and_peak_agree():
    assert logic.exit_tag_signals(["Target hit"], True)["conflict"] is False
    assert logic.exit_tag_signals(["Target never reached"], False)["conflict"] is False


def test_tag_is_suggested_when_none_was_applied_and_the_target_was_never_offered():
    assert logic.exit_tag_signals([], False)["suggestion"] == "Target never reached"


def test_no_suggestion_when_a_tag_already_exists():
    assert logic.exit_tag_signals(["Fear / Anxious"], False)["suggestion"] is None


def test_no_tag_signals_without_a_peak():
    sig = logic.exit_tag_signals(["Target hit"], None)
    assert sig == {"conflict": False, "suggestion": None}


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
    assert row["verdict"] is None          # no peak recorded yet
    assert row["excursion"] is None


def test_build_plan_execution_applies_the_peak(tmp_db, day_id):
    tid = _seed_trade(day_id, 1, "Long", 7715.0, 7731.25, 240.0,
                      [(3, 7715.0, 7688.5, 7760.0)])
    db.set_trade_mfe(tid, 7772.0, "during", 30)
    trades = db.get_trades_in_range(None, "2026-09-01", "2026-09-01")

    row = _rows_by_num(logic.build_plan_execution(trades))[1]
    assert row["verdict"] == "froze_at_target"
    assert row["excursion"]["kind"] == "give_back"
    assert row["excursion"]["dollars"] == 611.25
    assert row["target_offered"] is True


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


def test_summary_verdicts_are_counted_over_the_covered_set_only(tmp_db, day_id):
    a = _seed_trade(day_id, 1, "Long", 7715.0, 7731.25, 240.0,
                    [(3, 7715.0, 7688.5, 7760.0)])
    b = _seed_trade(day_id, 2, "Long", 7715.0, 7731.25, 240.0,
                    [(3, 7715.0, 7688.5, 7760.0)])
    _seed_trade(day_id, 3, "Long", 7715.0, 7731.25, 240.0,
                [(3, 7715.0, 7688.5, 7760.0)])   # no peak
    db.set_trade_mfe(a, 7772.0, "during", 30)
    db.set_trade_mfe(b, 7750.0, "after", 30)

    summary = logic.build_plan_execution(
        db.get_trades_in_range(None, "2026-09-01", "2026-09-01"))["summary"]

    assert summary["verdicts"]["froze_at_target"]["count"] == 1
    assert summary["verdicts"]["market_didnt_pay"]["count"] == 1
    assert summary["fear"]["count"] == 1, "market_didnt_pay must not count as fear"
    assert summary["verdicts_of"] == 2, (
        "denominator for verdict percentages is cut_early rows WITH a peak "
        "(2 of the 3 cut_early trades), not all cut_early rows (3) and not "
        "just the froze count (1)"
    )


def test_summary_target_realism_uses_the_covered_set(tmp_db, day_id):
    a = _seed_trade(day_id, 1, "Long", 7715.0, 7731.25, 240.0,
                    [(3, 7715.0, 7688.5, 7760.0)])
    b = _seed_trade(day_id, 2, "Long", 7715.0, 7731.25, 240.0,
                    [(3, 7715.0, 7688.5, 7760.0)])
    db.set_trade_mfe(a, 7772.0, "during", 30)   # offered
    db.set_trade_mfe(b, 7750.0, "after", 30)    # never offered

    realism = logic.build_plan_execution(
        db.get_trades_in_range(None, "2026-09-01", "2026-09-01"))["summary"]["realism"]

    assert realism["offered"] == 1
    assert realism["of"] == 2
    assert realism["pct"] == 50.0


def test_summary_survives_a_week_with_no_trades(tmp_db):
    result = logic.build_plan_execution([])
    assert result["rows"] == []
    assert result["summary"]["coverage"] == {"covered": 0, "total": 0}
    assert result["summary"]["realism"]["pct"] is None


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
    ('Bailed out - Reasses', 2). The migration must append the six new tags
    after position 2 without touching the three existing rows — reordering or
    renumbering would make save_tag_config's position-based rename cascade
    silently relabel real trades."""
    with db.get_conn() as conn:
        conn.execute("DELETE FROM tag_config WHERE group_id = 'exit'")
        for pos, tag in enumerate(
            ["Planned — Monitored Continuation", "Fear / Anxious", "Bailed out - Reasses"]
        ):
            conn.execute(
                "INSERT INTO tag_config (group_id, tag, position, enabled) "
                "VALUES ('exit', ?, ?, 1)", (tag, pos)
            )

    trade_id = db.insert_trade(db.upsert_day("2026-09-01", None), 1, "Long",
                               3, 7715.0, 7731.0, 240.0, "17:32", "18:02")
    db.set_trade_tags(trade_id, "exit", ["Bailed out - Reasses"])

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

    # the trade tagged 'Bailed out - Reasses' is untouched
    with db.get_conn() as conn:
        tt = conn.execute(
            "SELECT tag FROM trade_tags WHERE trade_id = ? AND group_id = 'exit'",
            (trade_id,)
        ).fetchall()
    assert [r["tag"] for r in tt] == ["Bailed out - Reasses"]


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
    assert pe["rows"][0]["verdict"] == "froze_at_target"
    assert pe["rows"][0]["tag_conflict"] is False
    assert "tag_suggestion" in pe["rows"][0]


def test_weekly_payload_plan_execution_is_empty_for_a_quiet_week(tmp_db):
    data = logic.build_weekly_review_data(None, "2026-08-31")
    assert data["plan_execution"]["rows"] == []
    assert data["plan_execution"]["summary"]["realism"]["pct"] is None
