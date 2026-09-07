"""Tag vocabulary edits must never silently relabel trades.

save_tag_config receives only an ordered list of strings from Settings, so it
infers renames by position. A deletion shifts every later tag up one slot,
which is indistinguishable from a rename — and the rename cascade then
rewrites trade_tags. These tests pin deletion as non-destructive while
keeping the genuine rename cascade working.
"""
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
