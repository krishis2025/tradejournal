"""Two ratios, neither carrying a verdict word.

  capture    = exit vs target   -- did I wait for my plan?      (behaviour)
  target_fit = peak vs target   -- was my plan reasonable?      (calibration)

The framework is explicit that an early exit is only a mistake if unjustified
by process, never merely because price continued afterwards. So these describe;
the trader's grade judges.
"""
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
