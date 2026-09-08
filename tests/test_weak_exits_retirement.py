"""F2 — the exit tag group is retired; nothing derives from it any more.

Two consumers of the retired `exit` tag group (`app_logic.compute_weekly_summary`'s
`planned`/`fear_bail` buckets and the `_det_weak_exits` trajectory detector) were
never migrated when the vocabulary was replaced by `management_issue` + `emotion`
+ target fit. Left alone they would read $0/$0 forever on new data while still
firing on the 90 historical exit-tagged trades in the real database — a phantom
"improvement to zero" in a tracked trajectory metric.

Controller ruling: retire both outright rather than repoint them at the new
fields. The A/B/C distribution and the B/C diagnosis block already answer the
question they were built to answer. This module pins that retirement down and
proves the trajectory cockpit tolerates the orphaned historical insight_log
rows (17 in the real database) rather than crashing on them.
"""
import database as db
import app_logic as logic


# ── The vocabulary is gone from the places that could read it ────────────────

def test_weak_exits_is_not_in_the_detector_registry():
    assert "weak_exits" not in logic.DETECTOR_REGISTRY
    assert "weak_exits" not in logic.tracked_detectors()


def test_weak_exits_is_not_in_the_intention_map():
    assert "weak_exits" not in logic._INTENTION_MAP


def test_weak_exits_is_not_in_the_behavior_phrasing_tables():
    assert "weak_exits" not in logic._BEHAVIOR_MID
    assert "weak_exits" not in logic._BEHAVIOR_ZERO


def test_det_weak_exits_function_no_longer_exists():
    assert not hasattr(logic, "_det_weak_exits")


def test_weekly_summary_no_longer_computes_planned_or_fear_bail(tmp_db, day_id):
    """The retired exit-tag buckets must not survive anywhere the summary is built,
    including on trades that still carry the old exit tags."""
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40")
    db.set_trade_tags(trade_id, "exit", ["Fear / Anxious"])
    trades = db.get_trades_in_range(None, "2026-01-01", "2026-12-31")
    summary = logic.compute_weekly_summary(trades)
    for gone in ("planned", "planned_net", "fear_bail", "fear_bail_net"):
        assert gone not in summary, f"{gone} should have been removed from the weekly summary"


def test_weekly_review_data_behavior_block_drops_the_retired_fields(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40")
    db.set_trade_tags(trade_id, "exit", ["Bailed out"])
    data = logic.build_weekly_review_data(None, "2026-09-01")
    for gone in ("planned_net", "fear_bail_net"):
        assert gone not in data["behavior"], f"{gone} should have been removed from behavior"


def test_planned_vs_fear_card_is_gone_from_the_weekly_review_template(client, tmp_db, day_id):
    """Render the page with an exit-tagged trade in the visible week and confirm
    the retired card never appears, even though the historical tag data does."""
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40")
    db.set_trade_tags(trade_id, "exit", ["Planned"])

    res = client.get("/weekly-review?week=2026-09-01")

    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Planned vs Fear" not in html


# ── The trajectory cockpit tolerates orphaned historical rows ────────────────

def _seed_qualifying_weeks(account_id, n, include_weak_exits):
    """Log `n` consecutive qualifying weeks for a still-tracked detector, matching
    the shape backfill_insight_log would have produced. When `include_weak_exits`,
    also plant one historical insight_log row for the retired 'weak_exits' id on
    the first week — exactly what the real database still holds (17 such rows)
    from before this detector was removed from the registry."""
    from datetime import date, timedelta
    monday = date(2026, 1, 5)  # a Monday
    weeks = []
    for i in range(n):
        week_start = (monday + timedelta(weeks=i)).isoformat()
        weeks.append(week_start)
        db.upsert_weekly_meta(account_id, week_start, total_trades=5, qualifying=True)
        db.upsert_insight_log(account_id, week_start, "came_to_me",
                               fired=1, magnitude=100.0, count=2, qualifying=1)
    if include_weak_exits:
        db.upsert_insight_log(account_id, weeks[0], "weak_exits",
                               fired=1, magnitude=-250.0, count=3, qualifying=1)
    return weeks[-1]


def test_build_cockpit_tolerates_a_historical_weak_exits_row(tmp_db):
    """The real database has 17 insight_log rows for the retired 'weak_exits'
    detector. build_cockpit must skip them, not crash, since the id no longer
    resolves in DETECTOR_REGISTRY."""
    anchor = _seed_qualifying_weeks(None, logic.MIN_QUALIFYING_FOR_TREND,
                                     include_weak_exits=True)

    cockpit = logic.build_cockpit(None, anchor)  # must not raise

    assert cockpit["visible"] is True
    all_detector_ids = (
        [t["detector_id"] for t in cockpit["strengths"]]
        + [t["detector_id"] for t in cockpit["leaks_focused"]]
        + [t["detector_id"] for t in cockpit["leaks_active"]]
        + [q["detector_id"] for q in cockpit["quiet"]]
    )
    assert "weak_exits" not in all_detector_ids


def test_classify_detector_state_tolerates_an_unknown_detector_id(tmp_db):
    """Direct call with a retired id (as a stale focus target or an old chart
    link might do) must not KeyError — DETECTOR_REGISTRY.get() already falls
    back to a generic label/polarity."""
    anchor = _seed_qualifying_weeks(None, logic.MIN_QUALIFYING_FOR_TREND,
                                     include_weak_exits=True)
    result = logic.classify_detector_state(None, "weak_exits", anchor)
    assert result["detector_id"] == "weak_exits"  # no crash


def test_intention_linkage_treats_a_retired_target_as_no_target(tmp_db):
    """An old intention that targeted 'weak_exits' before retirement must degrade
    to the no-target verdict rather than KeyError on DETECTOR_REGISTRY[targets]."""
    link = logic.intention_linkage(None, "weak_exits", "2026-01-05", "2026-03-01")
    assert link["has_target"] is False
    assert link["verdict"] == "no_target"
