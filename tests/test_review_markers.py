"""Configurable review markers.

Five review vocabularies live in tag_config with a stable key plus an editable
label. Trades store the key, so renaming a label is free — no cascade, no
migration, and none of the 4.8.1 rename/delete ambiguity.
"""
import sqlite3

import app_logic as logic
import database as db


def test_tag_config_gains_key_locked_and_entry_columns(tmp_db):
    cols = {r[1] for r in sqlite3.connect(tmp_db)
            .execute("PRAGMA table_info(tag_config)").fetchall()}

    assert {"tag_key", "locked", "at_entry"} <= cols


def test_defaults_declare_five_groups_with_the_expected_keys():
    groups = {g["id"]: g for g in logic.REVIEW_MARKER_GROUPS}

    assert list(groups) == ["management", "management_driver", "management_issue",
                            "emotion", "process_violation"]
    assert [t["key"] for t in groups["process_violation"]["tags"]] == [
        "none", "traded_outside_plan", "exceeded_risk", "revenge_trade", "overtraded"]
    assert [t["key"] for t in groups["emotion"]["tags"]] == [
        "calm", "fear_of_loss", "fear_of_giving_back", "greed",
        "frustration", "impatience", "overconfidence", "distracted"]


def test_management_is_fixed_set_and_both_options_locked():
    """The code branches on exactly two states, so a third would be unreadable.
    fixed_set blocks the Add box; locked blocks deletion of each option."""
    mgmt = [g for g in logic.REVIEW_MARKER_GROUPS if g["id"] == "management"][0]

    assert mgmt["fixed_set"] is True
    assert all(t["locked"] for t in mgmt["tags"])


def test_the_two_fear_states_are_the_only_ones_off_at_entry():
    """You cannot feel either before you hold a position."""
    emotion = [g for g in logic.REVIEW_MARKER_GROUPS if g["id"] == "emotion"][0]
    off = [t["key"] for t in emotion["tags"] if not t["at_entry"]]

    assert off == ["fear_of_loss", "fear_of_giving_back"]


def test_save_and_read_back_a_group(tmp_db):
    db.save_review_marker_group("process_violation", [
        {"key": "none", "label": "Clean", "at_entry": True},
        {"key": "overtraded", "label": "Overtraded", "at_entry": True},
    ])

    cfg = db.get_review_marker_config()["process_violation"]

    assert [t["key"] for t in cfg] == ["none", "overtraded"]
    assert cfg[0]["label"] == "Clean"


def test_saved_order_is_preserved(tmp_db):
    """Order is the order the chips appear in; it must survive a round trip."""
    db.save_review_marker_group("management_driver", [
        {"key": "pnl", "label": "P&L", "at_entry": True},
        {"key": "both", "label": "Both", "at_entry": True},
        {"key": "market_thesis", "label": "Market / Thesis", "at_entry": True},
    ])

    keys = [t["key"] for t in db.get_review_marker_config()["management_driver"]]

    assert keys == ["pnl", "both", "market_thesis"]


def test_saving_a_group_replaces_rather_than_appends(tmp_db):
    db.save_review_marker_group("management_driver", [
        {"key": "pnl", "label": "P&L", "at_entry": True}])
    db.save_review_marker_group("management_driver", [
        {"key": "both", "label": "Both", "at_entry": True}])

    keys = [t["key"] for t in db.get_review_marker_config()["management_driver"]]

    assert keys == ["both"]


def test_review_marker_rows_never_collide_with_legacy_tag_groups(tmp_db):
    """The five new groups share the tag_config table with the legacy
    label-addressed groups. get_tag_config() feeds the OLD settings cards and
    must not start returning review markers, or Technicals would sprout
    emotions."""
    db.save_review_marker_group("emotion", [
        {"key": "calm", "label": "Calm", "at_entry": True}])

    legacy = db.get_tag_config() or {}

    assert "emotion" not in legacy


def test_deleting_a_tag_does_not_touch_trades_that_used_it(tmp_db, day_id):
    """The 4.8.1 guard, re-pinned for keys.

    That bug came from save_tag_config reading a deletion as a rename — labels
    were identity, so removing one shifted the rest and the cascade relabelled
    11 real trades. Review markers store keys and run no cascade, so removing a
    tag from the vocabulary must leave every trade's stored key exactly as it
    was. The trade then renders via marker_label's key fallback.
    """
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, -50.0, "10:00", "10:30")
    db.set_trade_assessment(trade_id, grade="C", emotion="greed")

    db.save_review_marker_group("emotion", [
        {"key": "calm", "label": "Calm", "at_entry": True},
    ])

    with db.get_conn() as conn:
        stored = conn.execute("SELECT emotion FROM trades WHERE id = ?",
                              (trade_id,)).fetchone()[0]
    assert stored == "greed", "a vocabulary edit must never rewrite trade data"


def test_multi_flag_round_trips_and_defaults(tmp_db):
    assert db.get_group_multi("emotion", True) is True
    assert db.get_group_multi("management", False) is False

    db.set_group_multi("management", True)

    assert db.get_group_multi("management", False) is True
