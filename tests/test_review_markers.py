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
    assert [t["key"] for t in groups["management"]["tags"]] == [
        "followed", "deviated"]
    assert [t["key"] for t in groups["management_driver"]["tags"]] == [
        "market_thesis", "pnl", "both"]
    assert [t["key"] for t in groups["management_issue"]["tags"]] == [
        "none", "early_exit", "late_exit", "stop_change", "overmanaged",
        "under_managed", "premature_scale_out"]
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


def test_review_marker_config_excludes_legacy_rows(tmp_db):
    """The reverse of the collision guard above. Nothing previously covered
    get_review_marker_config() excluding a legacy, label-addressed row
    (tag_key NULL) — only that get_tag_config() excludes review-marker rows."""
    db.save_review_marker_group("emotion", [
        {"key": "calm", "label": "Calm", "at_entry": True}])

    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO tag_config (group_id, tag, position, enabled) "
            "VALUES ('technicals', 'Support/Resistance', 0, 1)")

    cfg = db.get_review_marker_config()

    assert "technicals" not in cfg


def test_deleting_a_tag_on_first_save_does_not_touch_trades(tmp_db, day_id):
    """Cheap companion to the two-save guard below: even a first-ever save for
    a group must not disturb a trade's stored key, though this shape alone
    cannot catch a cascade that diffs against previously-saved rows — see
    test_deleting_a_tag_does_not_touch_trades_that_used_it for that."""
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, -50.0, "10:00", "10:30")
    db.set_trade_assessment(trade_id, grade="C", emotion="greed")

    db.save_review_marker_group("emotion", [
        {"key": "calm", "label": "Calm", "at_entry": True},
    ])

    with db.get_conn() as conn:
        stored = conn.execute("SELECT emotion FROM trades WHERE id = ?",
                              (trade_id,)).fetchone()[0]
    assert stored == "greed", "a vocabulary edit must never rewrite trade data"


def test_deleting_a_tag_does_not_touch_trades_that_used_it(tmp_db, day_id):
    """The 4.8.1 guard, re-pinned for keys.

    That bug came from save_tag_config reading a deletion as a rename — labels
    were identity, so removing one shifted the rest and the cascade relabelled
    11 real trades. Review markers store keys and run no cascade, so removing a
    tag from the vocabulary must leave every trade's stored key exactly as it
    was. The trade then renders via marker_label's key fallback.

    Two saves, not one: the realistic cascade shape (the one that mirrors
    _cascade_tag_rename) diffs the new tags against the group's
    previously-saved rows, not against a first-ever save with no prior rows to
    diff against. So this test first establishes a custom vocabulary that
    includes the emotion the trade actually used, then saves again with that
    emotion removed — the edit-an-existing-vocabulary shape a cascade bug
    would actually trigger on.
    """
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, -50.0, "10:00", "10:30")
    db.set_trade_assessment(trade_id, grade="C", emotion="greed")

    db.save_review_marker_group("emotion", [
        {"key": "calm", "label": "Calm", "at_entry": True},
        {"key": "greed", "label": "Greed", "at_entry": True},
    ])

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


# ── Multi-value storage ───────────────────────────────────────────────────────

def test_decode_handles_arrays_scalars_and_blanks():
    """Scalars must decode too: the migration runs once, but a row written by an
    older build sitting in a backup, or restored later, would otherwise crash
    the review page rather than degrade."""
    assert db.decode_marker_list('["greed","impatience"]') == ["greed", "impatience"]
    assert db.decode_marker_list("greed") == ["greed"]
    assert db.decode_marker_list("") == []
    assert db.decode_marker_list(None) == []
    assert db.decode_marker_list("not json {") == ["not json {"]


def test_encode_round_trips_and_blanks_to_none():
    assert db.decode_marker_list(db.encode_marker_list(["greed"])) == ["greed"]
    assert db.encode_marker_list([]) is None


def test_migration_wraps_existing_scalars(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, 50.0, "10:00", "10:30")
    with db.get_conn() as conn:
        conn.execute("UPDATE trades SET emotion = 'greed', process_violation = 'overtraded' "
                     "WHERE id = ?", (trade_id,))
        conn.execute("DELETE FROM app_config WHERE key = 'migration_markers_to_lists'")

    db.init_db()

    with db.get_conn() as conn:
        row = conn.execute("SELECT emotion, process_violation FROM trades WHERE id = ?",
                           (trade_id,)).fetchone()
    assert row["emotion"] == '["greed"]'
    assert row["process_violation"] == '["overtraded"]'


def test_migration_is_idempotent_and_leaves_arrays_alone(tmp_db, day_id):
    """init_db runs on every request. A second pass must not wrap an array
    inside another array — the failure would be silent and unrecoverable."""
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, 50.0, "10:00", "10:30")
    with db.get_conn() as conn:
        conn.execute("UPDATE trades SET emotion = 'greed' WHERE id = ?", (trade_id,))
        conn.execute("DELETE FROM app_config WHERE key = 'migration_markers_to_lists'")

    db.init_db()
    with db.get_conn() as conn:
        conn.execute("DELETE FROM app_config WHERE key = 'migration_markers_to_lists'")
    db.init_db()

    with db.get_conn() as conn:
        row = conn.execute("SELECT emotion FROM trades WHERE id = ?", (trade_id,)).fetchone()
    assert row["emotion"] == '["greed"]'


def test_migration_leaves_blanks_and_nulls_alone(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, 50.0, "10:00", "10:30")
    with db.get_conn() as conn:
        conn.execute("UPDATE trades SET emotion = '', process_violation = NULL WHERE id = ?",
                     (trade_id,))
        conn.execute("DELETE FROM app_config WHERE key = 'migration_markers_to_lists'")

    db.init_db()

    with db.get_conn() as conn:
        row = conn.execute("SELECT emotion, process_violation FROM trades WHERE id = ?",
                           (trade_id,)).fetchone()
    assert row["emotion"] == ''
    assert row["process_violation"] is None


# ── Runtime vocabulary ────────────────────────────────────────────────────────

def test_configured_labels_override_defaults_without_touching_keys(tmp_db):
    """The whole point of keys: a rename changes what you read, never what is
    stored or branched on."""
    db.save_review_marker_group("process_violation", [
        {"key": "none", "label": "Clean", "at_entry": True},
        {"key": "overtraded", "label": "Traded too much", "at_entry": True},
    ])

    assert logic.marker_label("process_violation", "none") == "Clean"
    assert logic.marker_keys("process_violation") == ("none", "overtraded")


def test_unconfigured_groups_fall_back_to_defaults(tmp_db):
    assert logic.marker_label("emotion", "fear_of_loss") == "Fear of loss"
    assert "calm" in logic.marker_keys("emotion")


def test_marker_label_falls_back_to_the_key_for_a_retired_tag(tmp_db):
    """A trade tagged with an emotion later deleted from the vocabulary must
    still render something rather than raising on the review page."""
    assert logic.marker_label("emotion", "wistful") == "wistful"


def test_entry_emotions_follow_the_at_entry_flag(tmp_db):
    assert "fear_of_loss" not in logic.entry_emotion_keys()
    assert "calm" in logic.entry_emotion_keys()

    db.save_review_marker_group("emotion", [
        {"key": "calm", "label": "Calm", "at_entry": False},
        {"key": "fear_of_loss", "label": "Fear of loss", "at_entry": True},
    ])

    assert logic.entry_emotion_keys() == ("fear_of_loss",)


# ── Validation ────────────────────────────────────────────────────────────────

def test_multi_fields_accept_and_clean_a_list(tmp_db):
    cleaned, err = logic.validate_assessment(
        {"grade": "C", "emotion": ["greed", "impatience"]})

    assert err is None
    assert cleaned["emotion"] == ["greed", "impatience"]


def test_multi_fields_still_accept_a_bare_scalar(tmp_db):
    """The live_v2 review chain sends one value per click today; it must keep
    working while the UI catches up in Task 6."""
    cleaned, err = logic.validate_assessment({"grade": "C", "emotion": "greed"})

    assert err is None
    assert cleaned["emotion"] == ["greed"]


def test_an_unknown_key_is_still_rejected(tmp_db):
    """The vocabulary moved to config; it did not stop being closed."""
    cleaned, err = logic.validate_assessment({"grade": "C", "emotion": ["elated"]})

    assert cleaned == {}
    assert "emotion" in err


def test_none_wins_over_everything_else_in_a_multi_field(tmp_db):
    cleaned, err = logic.validate_assessment(
        {"grade": "C", "process_violation": ["none", "overtraded"]})

    assert err is None
    assert cleaned["process_violation"] == ["none"]


def test_any_real_violation_still_conflicts_with_an_a_grade(tmp_db):
    cleaned, err = logic.validate_assessment(
        {"grade": "A", "process_violation": ["none", "revenge_trade"]})

    assert cleaned == {}
    assert "A grade" in err


def test_the_a_grade_rule_survives_relabelling_none(tmp_db):
    """It keys off `none`, not the word 'None'."""
    db.save_review_marker_group("process_violation", [
        {"key": "none", "label": "Clean", "at_entry": True},
        {"key": "overtraded", "label": "Overtraded", "at_entry": True},
    ])

    _, ok_err = logic.validate_assessment({"grade": "A", "process_violation": ["none"]})
    _, bad_err = logic.validate_assessment({"grade": "A", "process_violation": ["overtraded"]})

    assert ok_err is None
    assert bad_err is not None


# ── Readers ───────────────────────────────────────────────────────────────────

def test_analytics_count_every_emotion_in_a_list(tmp_db):
    """Counting the raw column would score '["impatience","greed"]' as one
    exotic emotion rather than crediting `greed` at all.

    build_grade_analytics does not exist; the emotion tally actually lives in
    build_plan_execution(trades), which takes a plain list of trade dicts (no
    account or date range) and only ever indexes a row by `t["id"]` — every
    other field is read with .get(...) — so a minimal dict carrying `id`,
    `grade`, and `emotion` is enough to exercise it without touching the DB
    through insert_trade.

    `greed` is deliberately placed SECOND in both rows. A tally that only
    reads decoded[0] per trade would score `impatience` and `frustration`
    once each and `greed` zero times, so it fails this fixture instead of
    accidentally landing on the right answer by counting just the first
    element of every list. Do not "simplify" this back into a shape where
    the winning emotion happens to lead every list — that stops testing that
    every element counts, not just the first one.
    """
    rows = [
        {"id": 1, "grade": "C", "emotion": db.encode_marker_list(["impatience", "greed"])},
        {"id": 2, "grade": "C", "emotion": db.encode_marker_list(["frustration", "greed"])},
    ]

    result = logic.build_plan_execution(rows)

    assert result["summary"]["bc_diagnosis"]["top_emotion"][0] == "greed"
    assert result["summary"]["bc_diagnosis"]["top_emotion"][1] == 2


# ── API ───────────────────────────────────────────────────────────────────────

def test_get_returns_every_group_with_flags(client, tmp_db):
    groups = {g["id"]: g for g in client.get("/api/settings/review-markers").get_json()["groups"]}

    assert set(groups) == {"management", "management_driver", "management_issue",
                           "emotion", "process_violation"}
    assert groups["emotion"]["multi"] is True
    assert groups["management"]["fixed_set"] is True
    assert groups["management"]["tags"][0]["locked"] is True


def test_get_reflects_a_saved_customisation(client, tmp_db):
    """The GET route must read back what was actually saved, not the
    REVIEW_MARKER_GROUPS literal — a route that returned the constant would
    satisfy every static-flag assertion above while ignoring every save."""
    client.post("/api/settings/review-markers/process_violation", json={
        "tags": [{"key": "none", "label": "Clean slate", "at_entry": True},
                 {"key": "overtraded", "label": "Overtraded", "at_entry": True}],
        "multi": False})

    groups = {g["id"]: g for g in client.get("/api/settings/review-markers").get_json()["groups"]}

    assert groups["process_violation"]["multi"] is False
    labels = {t["key"]: t["label"] for t in groups["process_violation"]["tags"]}
    assert labels["none"] == "Clean slate"


def test_post_saves_labels_order_and_the_multi_flag(client, tmp_db):
    res = client.post("/api/settings/review-markers/process_violation", json={
        "tags": [{"key": "none", "label": "Clean", "at_entry": True},
                 {"key": "overtraded", "label": "Overtraded", "at_entry": True}],
        "multi": False})

    assert res.status_code == 200
    assert logic.marker_label("process_violation", "none") == "Clean"
    assert db.get_group_multi("process_violation", True) is False


def test_post_refuses_to_delete_a_locked_tag(client, tmp_db):
    """`none` is what the A-grade rule keys off. Losing it would make every
    A-grade save fail with a message about a value the trader cannot see."""
    res = client.post("/api/settings/review-markers/process_violation", json={
        "tags": [{"key": "overtraded", "label": "Overtraded", "at_entry": True}]})

    assert res.status_code == 400
    assert "none" in res.get_json()["error"]
    assert "none" in logic.marker_keys("process_violation")


def test_post_allows_renaming_a_locked_tag(client, tmp_db):
    """Locked blocks deletion, not renaming — only the key is load-bearing."""
    res = client.post("/api/settings/review-markers/process_violation", json={
        "tags": [{"key": "none", "label": "Clean", "at_entry": True},
                 {"key": "overtraded", "label": "Overtraded", "at_entry": True}]})

    assert res.status_code == 200
    assert logic.marker_label("process_violation", "none") == "Clean"


def test_post_refuses_a_new_tag_on_a_fixed_set_group(client, tmp_db):
    """Nothing branches on a third management state, so it could never be read."""
    res = client.post("/api/settings/review-markers/management", json={
        "tags": [{"key": "followed", "label": "Followed process", "at_entry": True},
                 {"key": "deviated", "label": "Deviated", "at_entry": True},
                 {"key": "partly", "label": "Partly", "at_entry": True}]})

    assert res.status_code == 400
    assert logic.marker_keys("management") == ("followed", "deviated")


def test_post_rejects_an_unknown_group(client, tmp_db):
    res = client.post("/api/settings/review-markers/not_a_group", json={"tags": []})

    assert res.status_code == 400


def test_post_refuses_to_empty_a_group_entirely(client, tmp_db):
    """A vocabulary with zero options is never valid — the review chain would
    render a question with no answers. Unlocked groups (emotion,
    management_driver) have no locked tag to catch this by accident."""
    res = client.post("/api/settings/review-markers/emotion", json={"tags": []})

    assert res.status_code == 400
    assert len(logic.marker_keys("emotion")) > 0


def test_post_rejects_duplicate_tag_keys(client, tmp_db):
    """Two tags keyed 'pnl' would both surface from get_review_marker_config,
    so the chip renders twice and marker_label becomes first-match-wins."""
    res = client.post("/api/settings/review-markers/management_driver", json={
        "tags": [{"key": "pnl", "label": "P&L", "at_entry": True},
                 {"key": "pnl", "label": "Profit and loss", "at_entry": True}]})

    assert res.status_code == 400
    assert logic.marker_keys("management_driver") == ("market_thesis", "pnl", "both")


def test_reset_restores_the_defaults(client, tmp_db):
    client.post("/api/settings/review-markers/process_violation", json={
        "tags": [{"key": "none", "label": "Clean", "at_entry": True}]})

    client.post("/api/settings/review-markers/process_violation/reset")

    assert logic.marker_label("process_violation", "none") == "None"
    assert len(logic.marker_keys("process_violation")) == 5


def test_legacy_tag_route_now_persists_its_multi_flag(client, tmp_db):
    """The Settings toggle has never saved anything: saveGroup posted {tags}
    only and the card re-rendered from a constant. Fixed here for the existing
    groups too, or the two new multi sections would be equally decorative."""
    client.post("/api/settings/tags/volume", json={"tags": ["Avg"], "multi": True})

    assert db.get_group_multi("volume", False) is True


def test_assessment_route_stores_a_multi_field_as_a_list(client, tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, -50.0, "10:00", "10:30")

    res = client.post(f"/api/trade/{trade_id}/assessment",
                      json={"grade": "C", "emotion": ["greed", "impatience"]})

    assert res.status_code == 200
    with db.get_conn() as conn:
        stored = conn.execute("SELECT emotion FROM trades WHERE id = ?", (trade_id,)).fetchone()[0]
    assert db.decode_marker_list(stored) == ["greed", "impatience"]


# ── Settings UI ───────────────────────────────────────────────────────────────

def _settings_html(client):
    return client.get("/settings").get_data(as_text=True)


def _rm_card(html, group_id):
    """The single review-marker card block for one group, div-balanced.

    Needed because every card carries the same classes — a bare substring check
    for a lock icon or an entry checkbox can pass against a neighbouring card
    instead of the one under test.
    """
    marker = 'data-group="{}"'.format(group_id)
    idx = html.index('class="rm-card"')
    while marker not in html[idx:html.index(">", idx) + 1]:
        idx = html.index('class="rm-card"', idx + 1)
    start = html.rfind("<div", 0, idx)
    pos, depth = start, 0
    while True:
        nxt_open = html.find("<div", pos)
        nxt_close = html.find("</div>", pos)
        if nxt_close == -1:
            raise AssertionError("unclosed rm-card for " + group_id)
        if nxt_open != -1 and nxt_open < nxt_close:
            depth += 1
            pos = nxt_open + 4
        else:
            depth -= 1
            pos = nxt_close + 6
            if depth == 0:
                return html[start:pos]


def test_review_markers_is_the_second_sub_tab(client, tmp_db):
    html = _settings_html(client)
    order = [html.index(label) for label in
             ("Technical Markers", "Review Markers", "Observation Markers", "Day Markers")]

    assert order == sorted(order)


def test_all_five_cards_render(client, tmp_db):
    html = _settings_html(client)

    for group_id in ("management", "management_driver", "management_issue",
                     "emotion", "process_violation"):
        assert 'data-group="{}"'.format(group_id) in html


def test_a_locked_row_has_no_delete_control_but_keeps_its_text_input(client, tmp_db):
    """Locked blocks deletion only — the label must stay editable."""
    card = _rm_card(_settings_html(client), "process_violation")
    none_row = card[card.index('data-key="none"'):]
    none_row = none_row[:none_row.index("</div>")]

    assert 'data-locked="true"' in none_row
    assert "rm-del" not in none_row
    assert "<input" in none_row


def test_an_unlocked_row_keeps_its_delete_control(client, tmp_db):
    card = _rm_card(_settings_html(client), "process_violation")
    row = card[card.index('data-key="overtraded"'):]
    row = row[:row.index("</div>")]

    assert "rm-del" in row


def test_the_entry_checkbox_appears_only_on_the_emotion_card(client, tmp_db):
    html = _settings_html(client)

    assert "rm-entry" in _rm_card(html, "emotion")
    assert "rm-entry" not in _rm_card(html, "process_violation")


def test_a_fixed_set_card_offers_no_add_box(client, tmp_db):
    """Adding a third management state would produce a value nothing reads."""
    assert "rm-add" not in _rm_card(_settings_html(client), "management")
    assert "rm-add" in _rm_card(_settings_html(client), "emotion")
