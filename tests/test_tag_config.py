"""Tag vocabulary edits must never silently relabel trades.

save_tag_config receives only an ordered list of strings from Settings, so it
infers renames by position. A deletion shifts every later tag up one slot,
which is indistinguishable from a rename — and the rename cascade then
rewrites trade_tags. These tests pin deletion as non-destructive while
keeping the genuine rename cascade working.
"""
import app_logic as logic
import database as db


def _seed_exit_vocab(day_id, vocab, tagged):
    """Install an exit vocabulary and tag one trade per entry in `tagged`."""
    with db.get_conn() as conn:
        conn.execute("DELETE FROM tag_config WHERE group_id = 'exit'")
        for i, tag in enumerate(vocab):
            conn.execute(
                "INSERT INTO tag_config (group_id, tag, position, enabled) "
                "VALUES ('exit', ?, ?, 1)", (tag, i)
            )
    for n, tag in enumerate(tagged, start=1):
        trade_id = db.insert_trade(day_id, n, "Long", 1, 7715.0, 7731.0, 80.0,
                                   "17:32", "18:02")
        db.set_trade_tags(trade_id, "exit", [tag])


def _exit_tag_counts():
    with db.get_conn() as conn:
        return {r["tag"]: r["n"] for r in conn.execute(
            "SELECT tag, COUNT(*) n FROM trade_tags WHERE group_id='exit' GROUP BY tag"
        ).fetchall()}


def test_deleting_a_middle_tag_does_not_relabel_its_trades(tmp_db, day_id):
    """The bug: deleting B shifts C up into slot 1, which reads as B->C."""
    _seed_exit_vocab(day_id, ["A", "B", "C"], ["B", "B", "C"])
    assert _exit_tag_counts() == {"B": 2, "C": 1}

    db.save_tag_config("exit", ["A", "C"])

    counts = _exit_tag_counts()
    assert counts.get("C") == 1, "C's trade count must not absorb B's trades"
    assert counts.get("B") == 2, "B's trades keep their tag; deleting a vocab entry is not a rename"


def test_deleting_the_first_tag_does_not_relabel_its_trades(tmp_db, day_id):
    """Position 0 is the worst case — it shifts the whole list."""
    _seed_exit_vocab(day_id, ["A", "B", "C"], ["A", "B"])

    db.save_tag_config("exit", ["B", "C"])

    counts = _exit_tag_counts()
    assert counts.get("A") == 1
    assert counts.get("B") == 1


def test_deleting_several_tags_at_once_does_not_relabel(tmp_db, day_id):
    _seed_exit_vocab(day_id, ["A", "B", "C", "D"], ["A", "B", "C", "D"])

    db.save_tag_config("exit", ["D"])

    assert _exit_tag_counts() == {"A": 1, "B": 1, "C": 1, "D": 1}


def test_renaming_a_tag_still_cascades_to_its_trades(tmp_db, day_id):
    """The cascade is a real feature and must survive the fix."""
    _seed_exit_vocab(day_id, ["A", "B", "C"], ["B", "B"])

    db.save_tag_config("exit", ["A", "B renamed", "C"])

    counts = _exit_tag_counts()
    assert counts.get("B renamed") == 2
    assert "B" not in counts


def test_reordering_tags_does_not_relabel(tmp_db, day_id):
    _seed_exit_vocab(day_id, ["A", "B", "C"], ["A", "B", "C"])

    db.save_tag_config("exit", ["C", "A", "B"])

    assert _exit_tag_counts() == {"A": 1, "B": 1, "C": 1}


def test_adding_a_tag_does_not_relabel(tmp_db, day_id):
    _seed_exit_vocab(day_id, ["A", "B"], ["A", "B"])

    db.save_tag_config("exit", ["A", "NEW", "B"])

    assert _exit_tag_counts() == {"A": 1, "B": 1}


def test_exit_group_is_gone_from_the_defaults():
    assert not any(g["id"] == "exit" for g in logic.TAG_GROUPS)


def test_exit_group_is_gone_from_get_tag_groups(tmp_db):
    """A DB override is returned wholesale, so the rows must be deleted too.

    get_tag_config() returns None (not {}) when tag_config is empty for every
    group, which it is on a fresh tmp_db — so the "exit" check is None-safe.
    """
    custom = db.get_tag_config()
    assert not custom or "exit" not in custom
    assert not any(g["id"] == "exit" for g in logic.get_tag_groups())


def test_retiring_the_group_leaves_trade_tags_untouched(tmp_db, day_id):
    """Historical trades keep the exit tags they were given."""
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, 50.0,
                               "10:00", "10:30")
    db.set_trade_tags(trade_id, "exit", ["Fear / Anxious"])

    db.init_db()

    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT tag FROM trade_tags WHERE trade_id = ? AND group_id = 'exit'",
            (trade_id,)).fetchall()
    assert [r["tag"] for r in rows] == ["Fear / Anxious"]


def test_the_deletion_is_one_shot_and_does_not_fight_the_append(tmp_db):
    """4.8.2 appends the exit vocabulary; this removes it. Running init_db
    repeatedly must not oscillate."""
    for _ in range(3):
        db.init_db()
    custom = db.get_tag_config()
    assert not custom or "exit" not in custom


def test_retiring_a_pre_existing_override_still_wipes_it_and_keeps_its_trade_tags(tmp_db, day_id):
    """Replays the real database's shape: an 'exit' override that predates the
    4.8.2 widened vocabulary, with a trade tagged on one of the original tags.
    On the very first init_db() after upgrade, the 4.8.2 append runs first
    (adding the six new tags to the pre-existing override), then this
    migration deletes the whole group in the same call — net effect is zero
    tag_config rows, same as any other database, and the append's own output
    never survives to be observed. trade_tags must still come through untouched."""
    # tmp_db already ran init_db() once (setting the retirement flag on an
    # empty table). Simulate an old database: clear the flag and seed a
    # pre-4.8.2 override.
    with db.get_conn() as conn:
        conn.execute("DELETE FROM app_config WHERE key = 'migration_exit_group_retired'")
        conn.execute("DELETE FROM tag_config WHERE group_id = 'exit'")
        for pos, tag in enumerate(
            ["Planned — Monitored Continuation", "Fear / Anxious", "Bailed out - Reasses"]
        ):
            conn.execute(
                "INSERT INTO tag_config (group_id, tag, position, enabled) "
                "VALUES ('exit', ?, ?, 1)", (tag, pos)
            )

    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7715.0, 7731.0, 80.0,
                               "17:32", "18:02")
    db.set_trade_tags(trade_id, "exit", ["Bailed out - Reasses"])

    db.init_db()  # append runs, then this migration wipes the group

    with db.get_conn() as conn:
        remaining = conn.execute(
            "SELECT * FROM tag_config WHERE group_id = 'exit'"
        ).fetchall()
        tt = conn.execute(
            "SELECT tag FROM trade_tags WHERE trade_id = ? AND group_id = 'exit'",
            (trade_id,)).fetchall()
    assert remaining == []
    assert [r["tag"] for r in tt] == ["Bailed out - Reasses"]

    # A second call must not resurrect anything (flag now set).
    db.init_db()
    with db.get_conn() as conn:
        still_gone = conn.execute(
            "SELECT * FROM tag_config WHERE group_id = 'exit'"
        ).fetchall()
    assert still_gone == []


def test_exit_tag_signals_is_removed():
    assert not hasattr(logic, "exit_tag_signals")
