"""Two ratios, neither carrying a verdict word.

  capture    = exit vs target   -- did I wait for my plan?      (behaviour)
  target_fit = peak vs target   -- was my plan reasonable?      (calibration)

The framework is explicit that an early exit is only a mistake if unjustified
by process, never merely because price continued afterwards. So these describe;
the trader's grade judges.
"""
import json

import database as db
import app_logic as logic


# ── compute_target_fit ───────────────────────────────────────────────────────

def test_target_fit_is_one_when_the_peak_lands_exactly_on_the_target():
    assert logic.compute_target_fit("Long", 7761.0, 7800.5, 7800.5) == 1.0


def test_target_fit_below_one_when_the_peak_fell_short():
    # planned 39.5 pts, peak reached 19.75 -> 0.5
    assert logic.compute_target_fit("Long", 7761.0, 7800.5, 7780.75) == 0.5


def test_target_fit_above_one_when_the_peak_ran_past():
    fit = logic.compute_target_fit("Long", 7761.0, 7800.5, 7820.25)
    assert round(fit, 4) == 1.5


def test_target_fit_is_direction_aware_for_shorts():
    # short: entry 7800, target 7760 (40 pts), peak 7780 is half way
    assert logic.compute_target_fit("Short", 7800.0, 7760.0, 7780.0) == 0.5
    # a peak BELOW the short target has run past it
    assert logic.compute_target_fit("Short", 7800.0, 7760.0, 7740.0) == 1.5


def test_target_fit_is_none_without_a_peak_or_target():
    assert logic.compute_target_fit("Long", 7761.0, 7800.5, None) is None
    assert logic.compute_target_fit("Long", 7761.0, None, 7800.5) is None


def test_target_fit_is_none_when_the_target_sits_within_a_tick_of_entry():
    assert logic.compute_target_fit("Long", 7761.0, 7761.1, 7800.0) is None


# ── classify_target_fit ──────────────────────────────────────────────────────

def test_target_fit_boundaries_with_the_default_bounds():
    b = (0.80, 1.20)
    assert logic.classify_target_fit(None, b) is None
    assert logic.classify_target_fit(0.50, b) == "too_far"
    assert logic.classify_target_fit(0.7999, b) == "too_far"
    assert logic.classify_target_fit(0.80, b) == "calibrated"
    assert logic.classify_target_fit(1.00, b) == "calibrated"
    assert logic.classify_target_fit(1.20, b) == "calibrated"
    assert logic.classify_target_fit(1.2001, b) == "too_close"


def test_target_fit_bounds_are_configurable(tmp_db):
    db.set_config("target_fit_low", "0.50")
    db.set_config("target_fit_high", "2.00")
    assert logic.get_target_fit_bounds() == (0.50, 2.00)
    assert logic.classify_target_fit(0.60) == "calibrated"


def test_target_fit_bounds_fall_back_when_config_is_junk(tmp_db):
    db.set_config("target_fit_low", "")
    db.set_config("target_fit_high", "nonsense")
    assert logic.get_target_fit_bounds() == (0.80, 1.20)


# ── capture_band ─────────────────────────────────────────────────────────────

def test_capture_bands_at_the_boundaries(tmp_db):
    assert logic.capture_band(0.10, 100.0) == "red"
    assert logic.capture_band(0.5999, 100.0) == "red"
    assert logic.capture_band(0.60, 100.0) == "orange"
    assert logic.capture_band(0.7999, 100.0) == "orange"
    assert logic.capture_band(0.80, 100.0) == "green"
    assert logic.capture_band(1.10, 100.0) == "green"
    assert logic.capture_band(1.1001, 100.0) == "blue"


def test_capture_band_is_blank_on_a_loss(tmp_db):
    """A capture ratio on a loser compares an exit against a target that was
    never in play."""
    assert logic.capture_band(0.90, -250.0) is None


def test_capture_band_renders_on_a_scratch(tmp_db):
    """A scratch is not a loss."""
    assert logic.capture_band(0.90, 0.0) == "green"


def test_capture_band_is_none_without_a_capture(tmp_db):
    assert logic.capture_band(None, 100.0) is None


def test_capture_mid_is_configurable(tmp_db):
    db.set_config("plan_capture_mid", "0.95")
    assert logic.get_plan_capture_mid() == 0.95
    assert logic.capture_band(0.90, 100.0) == "orange"


def test_capture_band_accepts_prefetched_bounds_and_mid():
    """No tmp_db fixture here: proves this call never opens the database."""
    assert logic.capture_band(0.90, 100.0, bounds=(0.60, 1.10), mid=0.80) == "green"


def _seed(day_id, num, direction="Long", entry=7761.0, exit_=7795.5, pnl=1035.0,
          fills=((3, 7756.0, 7736.0, 7786.0), (3, 7766.0, 7746.0, 7815.0)),
          **assessment):
    qty = sum(f[0] for f in fills)
    trade_id = db.insert_trade(day_id, num, direction, qty, entry, exit_, pnl,
                               "10:05", "10:40",
                               execution_json=json.dumps({"instrument": "MES"}),
                               **assessment)
    entry_side = "Buy" if direction == "Long" else "Sell"
    exit_side = "Sell" if direction == "Long" else "Buy"
    for q, price, stop, target in fills:
        db.insert_fill(trade_id, "10:05", entry_side, q, price,
                       stop_price=stop, stop_source="entered",
                       target_price=target, target_source="entered")
    db.insert_fill(trade_id, "10:40", exit_side, qty, exit_, exit_type="manual_exit")
    return trade_id


def _rows(day="2026-09-07"):
    return logic.build_plan_execution(db.get_trades_in_range(None, day, day))


def test_rows_carry_the_assessment_fields(tmp_db):
    day_id = db.upsert_day("2026-09-07", None)
    _seed(day_id, 1, grade="B", management="deviated",
          management_issue="early_exit", emotion="fear_of_giving_back")

    row = _rows()["rows"][0]

    assert row["grade"] == "B"
    assert row["management"] == "deviated"
    assert row["management_issue"] == "early_exit"
    assert row["emotion"] == "fear_of_giving_back"


def test_rows_carry_target_fit_and_capture_band(tmp_db):
    day_id = db.upsert_day("2026-09-07", None)
    tid = _seed(day_id, 1)
    db.set_trade_mfe(tid, 7809.5, "after", 30)

    row = _rows()["rows"][0]

    assert round(row["target_fit"], 4) == 1.2278   # (7809.5-7761)/(7800.5-7761)
    assert row["target_fit_class"] == "too_close"
    assert row["capture_band"] == "green"           # capture 0.873, profitable


def test_the_verdict_machinery_is_gone(tmp_db):
    """Removed by design: these judged an exit from price data alone."""
    day_id = db.upsert_day("2026-09-07", None)
    tid = _seed(day_id, 1)
    db.set_trade_mfe(tid, 7809.5, "after", 30)

    result = _rows()
    row = result["rows"][0]

    for gone in ("verdict", "target_offered", "tag_conflict", "tag_suggestion"):
        assert gone not in row, f"{gone} should have been removed from the row"
    for gone in ("verdicts", "verdicts_of", "fear", "greed", "realism"):
        assert gone not in result["summary"], f"{gone} should have been removed"


def test_summary_reports_the_grade_distribution_and_its_denominator(tmp_db):
    day_id = db.upsert_day("2026-09-07", None)
    _seed(day_id, 1, grade="A", pnl=500.0)
    _seed(day_id, 2, grade="B", pnl=-200.0)
    _seed(day_id, 3, grade="B", pnl=300.0)
    _seed(day_id, 4)                      # ungraded

    s = _rows()["summary"]

    assert s["grades"]["A"]["count"] == 1
    assert s["grades"]["B"]["count"] == 2
    assert s["grades"]["C"]["count"] == 0
    assert s["grades"]["B"]["net"] == 100.0
    assert s["graded_of"] == 3, "denominator is graded trades, not all trades"


def test_grade_distribution_ignores_pnl_as_evidence(tmp_db):
    """P&L has no vote: a losing trade can be A-game."""
    day_id = db.upsert_day("2026-09-07", None)
    _seed(day_id, 1, grade="A", pnl=-400.0)

    s = _rows()["summary"]

    assert s["grades"]["A"]["count"] == 1
    assert s["grades"]["A"]["net"] == -400.0


def test_summary_reports_the_target_fit_distribution(tmp_db):
    day_id = db.upsert_day("2026-09-07", None)
    a = _seed(day_id, 1)
    b = _seed(day_id, 2)
    c = _seed(day_id, 3)
    db.set_trade_mfe(a, 7770.0, "during", 30)    # fit 0.23 -> too_far
    db.set_trade_mfe(b, 7800.0, "after", 30)     # fit 0.987 -> calibrated
    db.set_trade_mfe(c, 7830.0, "after", 30)     # fit 1.747 -> too_close

    d = _rows()["summary"]["target_fit_dist"]

    assert d["too_far"] == 1
    assert d["calibrated"] == 1
    assert d["too_close"] == 1
    assert d["of"] == 3


def test_target_fit_counts_a_losing_trade(tmp_db):
    """Capture is blanked on a loss; target fit is not. 'Was my target
    reasonable' is a fair question on a loser."""
    day_id = db.upsert_day("2026-09-07", None)
    tid = _seed(day_id, 1, exit_=7740.0, pnl=-630.0)
    db.set_trade_mfe(tid, 7800.0, "during", 30)

    row = _rows()["rows"][0]
    assert row["capture_band"] is None
    assert row["target_fit_class"] == "calibrated"
    assert _rows()["summary"]["target_fit_dist"]["of"] == 1


def test_bc_diagnosis_names_the_commonest_issue_and_emotion(tmp_db):
    day_id = db.upsert_day("2026-09-07", None)
    _seed(day_id, 1, grade="B", management="deviated",
          management_issue="early_exit", emotion="fear_of_giving_back")
    _seed(day_id, 2, grade="C", management="deviated",
          management_issue="early_exit", emotion="frustration")
    _seed(day_id, 3, grade="B", management="deviated",
          management_issue="stop_change", emotion="fear_of_giving_back")
    _seed(day_id, 4, grade="A", management="followed",
          management_issue="none", emotion="calm")

    d = _rows()["summary"]["bc_diagnosis"]

    assert d["of"] == 3, "A-game trades are not part of the diagnosis"
    assert d["top_issue"] == ("early_exit", 2)
    assert d["top_emotion"] == ("fear_of_giving_back", 2)


def test_bc_diagnosis_is_empty_when_the_week_has_no_b_or_c(tmp_db):
    day_id = db.upsert_day("2026-09-07", None)
    _seed(day_id, 1, grade="A", management="followed", emotion="calm")

    d = _rows()["summary"]["bc_diagnosis"]

    assert d["of"] == 0
    assert d["top_issue"] is None
    assert d["top_emotion"] is None


def test_empty_week_produces_no_distributions(tmp_db):
    result = logic.build_plan_execution([])
    assert result["rows"] == []
    assert result["summary"]["graded_of"] == 0
    assert result["summary"]["target_fit_dist"]["of"] == 0


def test_day_score_no_longer_uses_the_execution_score(tmp_db, day_id):
    """The 5-point score is retired; the day grade reflects the day process
    checklist alone."""
    import json as _json
    db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, 50.0, "10:00", "10:30",
                    execution_score_json=_json.dumps({"version": 1, "score": 1}))
    trades = db.get_trades_for_day(day_id)

    with_exec = logic.compute_combined_day_score('{"a": true, "b": true}', trades)
    without = logic.compute_combined_day_score('{"a": true, "b": true}', [])

    assert with_exec == without, "trade execution scores must not move the day grade"
