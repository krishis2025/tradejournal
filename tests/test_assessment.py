"""A/B/C grade and the five diagnostic fields.

Seven scalar columns rather than a JSON blob: every question the framework
asks is a GROUP BY over two of these, and the existing execution_score_json
is exactly the blob shape that makes those questions awkward.
"""
import app_logic as logic
import database as db

ASSESSMENT_COLS = ["grade", "management", "management_issue", "emotion",
                   "emotion_entry", "process_violation", "pre_tags_late"]


def _cols(table):
    with db.get_conn() as conn:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def test_assessment_columns_exist_on_both_tables(tmp_db):
    for table in ("trades", "live_trades"):
        cols = _cols(table)
        for c in ASSESSMENT_COLS:
            assert c in cols, f"{c} missing from {table}"


def test_assessment_migration_is_rerunnable(tmp_db):
    db.init_db()
    db.init_db()
    assert _cols("trades").count("grade") == 1
    assert _cols("live_trades").count("emotion_entry") == 1


def test_assessment_fields_default_to_null(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40")
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    for c in ASSESSMENT_COLS[:-1]:
        assert row[c] is None, f"{c} should default to NULL, not a coerced value"
    assert row["pre_tags_late"] == 0


def test_insert_trade_accepts_the_assessment_fields(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40",
                               grade="B", management="deviated",
                               management_issue="early_exit",
                               emotion="fear_of_giving_back",
                               emotion_entry="calm",
                               process_violation="none",
                               pre_tags_late=1)
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    assert row["grade"] == "B"
    assert row["management"] == "deviated"
    assert row["management_issue"] == "early_exit"
    assert row["emotion"] == "fear_of_giving_back"
    assert row["emotion_entry"] == "calm"
    assert row["process_violation"] == "none"
    assert row["pre_tags_late"] == 1


def test_set_trade_assessment_writes_a_subset(tmp_db, day_id):
    """Diagnosis happens after the session, one field at a time."""
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40", grade="A")

    db.set_trade_assessment(trade_id, management="followed", emotion="calm")

    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    assert row["management"] == "followed"
    assert row["emotion"] == "calm"
    assert row["grade"] == "A", "untouched fields must survive a partial write"


def test_set_trade_assessment_ignores_unknown_fields(tmp_db, day_id):
    """The route passes a request body through; an unknown key must not
    become SQL."""
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40")
    db.set_trade_assessment(trade_id, grade="A", nonsense="x'; DROP TABLE trades;--")
    with db.get_conn() as conn:
        row = conn.execute("SELECT grade FROM trades WHERE id = ?", (trade_id,)).fetchone()
        assert row["grade"] == "A"
        assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1


def test_set_trade_assessment_with_no_known_fields_is_a_noop(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40", grade="A")
    db.set_trade_assessment(trade_id, nonsense="x")
    with db.get_conn() as conn:
        assert conn.execute("SELECT grade FROM trades WHERE id = ?",
                            (trade_id,)).fetchone()["grade"] == "A"


def test_vocabularies_match_the_spec():
    assert logic.GRADES == ("A", "B", "C")
    assert logic.MANAGEMENT == ("followed", "deviated")
    assert logic.MANAGEMENT_ISSUES == (
        "none", "early_exit", "late_exit", "stop_change",
        "overmanaged", "under_managed", "premature_scale_out")
    assert logic.EMOTIONS == (
        "calm", "fear_of_loss", "fear_of_giving_back", "greed",
        "frustration", "impatience", "overconfidence", "distracted")
    assert logic.PROCESS_VIOLATIONS == (
        "none", "traded_outside_plan", "exceeded_risk", "revenge_trade", "overtraded")


def test_entry_emotions_exclude_the_two_that_need_an_open_position():
    """Fear of loss and fear of giving back cannot precede a trade."""
    assert "fear_of_loss" not in logic.ENTRY_EMOTIONS
    assert "fear_of_giving_back" not in logic.ENTRY_EMOTIONS
    assert set(logic.ENTRY_EMOTIONS) < set(logic.EMOTIONS)
    assert len(logic.ENTRY_EMOTIONS) == 6


def test_validate_accepts_a_good_payload():
    cleaned, err = logic.validate_assessment(
        {"grade": "B", "management": "deviated", "management_issue": "early_exit",
         "emotion": "fear_of_giving_back", "process_violation": "revenge_trade"})
    assert err is None
    assert cleaned["grade"] == "B"


def test_validate_rejects_a_value_outside_its_vocabulary():
    _, err = logic.validate_assessment({"grade": "D"})
    assert err is not None and "grade" in err


def test_validate_rejects_management_issue_without_deviated():
    """The issue describes what the deviation was; it is meaningless otherwise."""
    _, err = logic.validate_assessment(
        {"management": "followed", "management_issue": "early_exit"})
    assert err is not None and "management_issue" in err


def test_validate_allows_management_issue_none_when_followed():
    cleaned, err = logic.validate_assessment(
        {"management": "followed", "management_issue": "none"})
    assert err is None
    assert cleaned["management_issue"] == "none"


def test_validate_rejects_a_process_violation_on_an_a_grade():
    """The field is only asked on B or C; an A-game violation is a contradiction."""
    _, err = logic.validate_assessment(
        {"grade": "A", "process_violation": "revenge_trade"})
    assert err is not None and "process_violation" in err


def test_validate_allows_process_violation_none_on_an_a_grade():
    cleaned, err = logic.validate_assessment({"grade": "A", "process_violation": "none"})
    assert err is None


def test_validate_rejects_a_fear_emotion_at_entry():
    _, err = logic.validate_assessment({"emotion_entry": "fear_of_giving_back"})
    assert err is not None and "emotion_entry" in err


def test_validate_drops_unknown_keys_without_erroring():
    cleaned, err = logic.validate_assessment({"grade": "A", "sneaky": "value"})
    assert err is None
    assert "sneaky" not in cleaned


def test_validate_accepts_an_empty_payload():
    cleaned, err = logic.validate_assessment({})
    assert err is None and cleaned == {}


def test_post_assessment_to_a_journal_trade(client, tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40")
    res = client.post(f"/api/trade/{trade_id}/assessment",
                      json={"grade": "A", "management": "followed", "emotion": "calm"})
    assert res.status_code == 200
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    assert (row["grade"], row["management"], row["emotion"]) == ("A", "followed", "calm")


def test_post_assessment_rejects_an_invalid_value(client, tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40")
    res = client.post(f"/api/trade/{trade_id}/assessment", json={"grade": "D"})
    assert res.status_code == 400
    with db.get_conn() as conn:
        assert conn.execute("SELECT grade FROM trades WHERE id = ?",
                            (trade_id,)).fetchone()["grade"] is None


def test_post_assessment_to_a_live_trade(client, tmp_db):
    live_id = db.create_live_trade(None, "Long", "MES", 7756.0, "10:05", 3, "full")
    res = client.post(f"/api/live/{live_id}/assessment",
                      json={"grade": "C", "process_violation": "revenge_trade"})
    assert res.status_code == 200
    lt = db.get_live_trade(live_id)
    assert lt["grade"] == "C"
    assert lt["process_violation"] == "revenge_trade"


# ── Cross-field rules must see stored state, not just this payload ──────────
# Diagnosis happens one field at a time (set_trade_assessment's own docstring
# says so), so a rule that only looks at the current payload both false-
# rejects a legitimate single-field edit and false-accepts a forbidden
# combination when the conflicting half is already in the database.

def test_validate_assessment_with_no_current_arg_behaves_as_before():
    cleaned, err = logic.validate_assessment({"grade": "A", "process_violation": "none"})
    assert err is None
    assert cleaned == {"grade": "A", "process_violation": "none"}


def test_validate_assessment_merges_current_state_for_the_management_issue_rule():
    """management='deviated' is already stored; sending the issue alone must pass."""
    cleaned, err = logic.validate_assessment(
        {"management_issue": "early_exit"}, current={"management": "deviated"})
    assert err is None
    assert cleaned == {"management_issue": "early_exit"}


def test_validate_assessment_merges_current_state_to_catch_a_stranded_violation():
    """grade='A' is already stored; adding a violation alone must be rejected."""
    cleaned, err = logic.validate_assessment(
        {"process_violation": "revenge_trade"}, current={"grade": "A"})
    assert err is not None and "process_violation" in err


def test_post_assessment_accepts_a_single_field_when_deviated_already_stored(client, tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40")
    client.post(f"/api/trade/{trade_id}/assessment", json={"management": "deviated"})
    res = client.post(f"/api/trade/{trade_id}/assessment",
                      json={"management_issue": "early_exit"})
    assert res.status_code == 200
    with db.get_conn() as conn:
        row = conn.execute("SELECT management, management_issue FROM trades WHERE id = ?",
                            (trade_id,)).fetchone()
    assert (row["management"], row["management_issue"]) == ("deviated", "early_exit")


def test_post_assessment_rejects_a_violation_against_a_stored_a_grade(client, tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40")
    client.post(f"/api/trade/{trade_id}/assessment", json={"grade": "A"})
    res = client.post(f"/api/trade/{trade_id}/assessment",
                      json={"process_violation": "revenge_trade"})
    assert res.status_code == 400
    with db.get_conn() as conn:
        assert conn.execute("SELECT process_violation FROM trades WHERE id = ?",
                            (trade_id,)).fetchone()["process_violation"] is None


def test_post_assessment_rejects_a_grade_change_that_strands_a_stored_violation(client, tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40")
    client.post(f"/api/trade/{trade_id}/assessment",
               json={"grade": "B", "process_violation": "revenge_trade"})
    res = client.post(f"/api/trade/{trade_id}/assessment", json={"grade": "A"})
    assert res.status_code == 400
    with db.get_conn() as conn:
        assert conn.execute("SELECT grade FROM trades WHERE id = ?",
                            (trade_id,)).fetchone()["grade"] == "B"


def test_post_assessment_allows_clearing_the_violation_in_the_same_request(client, tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40")
    client.post(f"/api/trade/{trade_id}/assessment",
               json={"grade": "B", "process_violation": "revenge_trade"})
    res = client.post(f"/api/trade/{trade_id}/assessment",
                      json={"grade": "A", "process_violation": "none"})
    assert res.status_code == 200
    with db.get_conn() as conn:
        row = conn.execute("SELECT grade, process_violation FROM trades WHERE id = ?",
                            (trade_id,)).fetchone()
    assert (row["grade"], row["process_violation"]) == ("A", "none")


def test_post_assessment_allows_clearing_deviation_and_issue_together(client, tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40")
    client.post(f"/api/trade/{trade_id}/assessment",
               json={"management": "deviated", "management_issue": "early_exit"})
    res = client.post(f"/api/trade/{trade_id}/assessment",
                      json={"management": "followed", "management_issue": "none"})
    assert res.status_code == 200
    with db.get_conn() as conn:
        row = conn.execute("SELECT management, management_issue FROM trades WHERE id = ?",
                            (trade_id,)).fetchone()
    assert (row["management"], row["management_issue"]) == ("followed", "none")


def test_post_assessment_live_accepts_a_single_field_when_deviated_already_stored(client, tmp_db):
    live_id = db.create_live_trade(None, "Long", "MES", 7756.0, "10:05", 3, "full")
    client.post(f"/api/live/{live_id}/assessment", json={"management": "deviated"})
    res = client.post(f"/api/live/{live_id}/assessment",
                      json={"management_issue": "early_exit"})
    assert res.status_code == 200
    lt = db.get_live_trade(live_id)
    assert (lt["management"], lt["management_issue"]) == ("deviated", "early_exit")


def test_post_assessment_live_rejects_a_violation_against_a_stored_a_grade(client, tmp_db):
    live_id = db.create_live_trade(None, "Long", "MES", 7756.0, "10:05", 3, "full")
    client.post(f"/api/live/{live_id}/assessment", json={"grade": "A"})
    res = client.post(f"/api/live/{live_id}/assessment",
                      json={"process_violation": "revenge_trade"})
    assert res.status_code == 400
    lt = db.get_live_trade(live_id)
    assert lt["process_violation"] is None
