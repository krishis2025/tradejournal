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
