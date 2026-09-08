"""A/B/C grade and the five diagnostic fields.

Seven scalar columns rather than a JSON blob: every question the framework
asks is a GROUP BY over two of these, and the existing execution_score_json
is exactly the blob shape that makes those questions awkward.
"""
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
