"""Weekly market board — storage, percent maths, and rendering.

The board holds two typed prices per instrument per week and computes the
percent from them on read. Nothing derived is stored.
"""
import sqlite3

import app_logic as logic
import database as db


def test_table_exists_after_init(tmp_db):
    cols = {r[1] for r in sqlite3.connect(tmp_db)
            .execute("PRAGMA table_info(weekly_market_prices)").fetchall()}

    assert {"account_id", "week_start", "instrument",
            "monday_open", "current"} <= cols


def test_upsert_round_trips_both_prices(tmp_db):
    db.upsert_weekly_market_price(None, "2026-09-14", "XLK", 265.40, 266.75)

    rows = db.get_weekly_market_prices(None, "2026-09-14")

    assert rows["XLK"]["monday_open"] == 265.40
    assert rows["XLK"]["current"] == 266.75


def test_upsert_replaces_rather_than_duplicating(tmp_db):
    """UNIQUE(account_id, week_start, instrument) means a second write to the
    same cell must update, not append — otherwise a Wednesday refresh would
    stack a new row every time and the board would read a stale one."""
    db.upsert_weekly_market_price(None, "2026-09-14", "XLK", 265.40, 266.75)
    db.upsert_weekly_market_price(None, "2026-09-14", "XLK", 265.40, 268.10)

    rows = db.get_weekly_market_prices(None, "2026-09-14")
    count = sqlite3.connect(tmp_db).execute(
        "SELECT COUNT(*) FROM weekly_market_prices WHERE instrument = 'XLK'"
    ).fetchone()[0]

    assert count == 1
    assert rows["XLK"]["current"] == 268.10


def test_weeks_are_isolated(tmp_db):
    """Reading the board for one week must never surface another week's
    numbers — the whole point is comparing this week against last."""
    db.upsert_weekly_market_price(None, "2026-09-07", "XLK", 260.00, 262.00)
    db.upsert_weekly_market_price(None, "2026-09-14", "XLK", 265.40, 266.75)

    assert db.get_weekly_market_prices(None, "2026-09-07")["XLK"]["current"] == 262.00
    assert db.get_weekly_market_prices(None, "2026-09-14")["XLK"]["current"] == 266.75


def test_accounts_are_isolated(tmp_db):
    """The legacy NULL account is a real account here, not 'any account'."""
    acct = db.create_account("Test")
    db.upsert_weekly_market_price(None, "2026-09-14", "XLK", 265.40, 266.75)
    db.upsert_weekly_market_price(acct, "2026-09-14", "XLK", 100.00, 101.00)

    assert db.get_weekly_market_prices(None, "2026-09-14")["XLK"]["current"] == 266.75
    assert db.get_weekly_market_prices(acct, "2026-09-14")["XLK"]["current"] == 101.00


def test_migration_is_rerunnable(tmp_db):
    """init_db() runs on every request, so it must be safe over existing data."""
    db.upsert_weekly_market_price(None, "2026-09-14", "XLK", 265.40, 266.75)

    db.init_db()
    db.init_db()

    assert db.get_weekly_market_prices(None, "2026-09-14")["XLK"]["current"] == 266.75


def test_upsert_replaces_rather_than_duplicating_real_account(tmp_db):
    """The other branch of upsert_weekly_market_price — a real, non-null
    account — relies on the schema UNIQUE + ON CONFLICT to replace rather
    than duplicate. test_upsert_replaces_rather_than_duplicating only ever
    exercises the None-account UPDATE-then-INSERT branch, so this path was
    unproven except incidentally, by an unrelated test raising an exception
    when the schema constraint was mutated away."""
    acct = db.create_account("Test")
    db.upsert_weekly_market_price(acct, "2026-09-14", "XLK", 265.40, 266.75)
    db.upsert_weekly_market_price(acct, "2026-09-14", "XLK", 265.40, 268.10)

    rows = db.get_weekly_market_prices(acct, "2026-09-14")
    count = sqlite3.connect(tmp_db).execute(
        "SELECT COUNT(*) FROM weekly_market_prices WHERE instrument = 'XLK' AND account_id = ?",
        (acct,)
    ).fetchone()[0]

    assert count == 1
    assert rows["XLK"]["current"] == 268.10


def test_null_account_write_does_not_clobber_real_account_row(tmp_db):
    """The None-account branch of upsert_weekly_market_price UPDATEs by
    `account_id IS NULL AND week_start = ? AND instrument = ?`. If the
    `account_id IS NULL` clause were ever dropped, that UPDATE would match
    on week_start + instrument alone and silently overwrite a real
    account's row instead of inserting a separate NULL-account row —
    the real account would then read the null account's numbers, the
    null account would read nothing, and the row count would stay 1,
    so nothing would look wrong without this test."""
    acct = db.create_account("Test")
    db.upsert_weekly_market_price(acct, "2026-09-14", "XLK", 100.00, 101.00)
    db.upsert_weekly_market_price(None, "2026-09-14", "XLK", 265.40, 266.75)

    count = sqlite3.connect(tmp_db).execute(
        "SELECT COUNT(*) FROM weekly_market_prices "
        "WHERE week_start = '2026-09-14' AND instrument = 'XLK'"
    ).fetchone()[0]

    assert count == 2
    assert db.get_weekly_market_prices(acct, "2026-09-14")["XLK"]["current"] == 101.00
    assert db.get_weekly_market_prices(None, "2026-09-14")["XLK"]["current"] == 266.75


# ── Instrument list ───────────────────────────────────────────────────────────

def test_board_carries_twenty_instruments_in_fixed_order():
    keys = [k for k, _, _ in logic.WEEKLY_BOARD]

    assert len(keys) == 20
    assert keys[:3] == ["SPX", "NDX", "RUT"]
    # SMH sits directly after Tech, by request
    assert keys[3:5] == ["XLK", "SMH"]
    assert keys[-5:] == ["TLT", "TNX", "VIX", "GC", "CL"]


def test_board_groups_are_three_twelve_five():
    groups = {}
    for _, _, g in logic.WEEKLY_BOARD:
        groups[g] = groups.get(g, 0) + 1

    assert groups == {"indices": 3, "sectors": 12, "macro": 5}


# ── Price parsing ─────────────────────────────────────────────────────────────

def test_parse_price_accepts_typed_thousands_separators():
    """'7,656.98' is what actually gets typed, and float() rejects it."""
    assert logic.parse_price("7,656.98") == 7656.98
    assert logic.parse_price("  4.79 ") == 4.79
    assert logic.parse_price(265.4) == 265.4


def test_parse_price_treats_blank_as_unset():
    assert logic.parse_price("") is None
    assert logic.parse_price("   ") is None
    assert logic.parse_price(None) is None


def test_parse_price_rejects_junk_and_non_finite():
    """'nan' and 'inf' both survive float() and would poison every percent
    downstream without ever raising."""
    import pytest
    for bad in ("abc", "1.2.3", "nan", "inf", "-inf"):
        with pytest.raises(ValueError):
            logic.parse_price(bad)


# ── Percent ───────────────────────────────────────────────────────────────────

def test_pct_is_percent_of_the_monday_open():
    assert round(logic.board_pct(4.61, 4.79), 2) == 3.90
    assert round(logic.board_pct(100.0, 99.0), 2) == -1.0


def test_pct_is_none_when_either_price_is_missing():
    assert logic.board_pct(None, 100.0) is None
    assert logic.board_pct(100.0, None) is None
    assert logic.board_pct(None, None) is None


def test_pct_is_none_when_the_open_is_zero():
    """A blank open is the normal state of every instrument on Monday morning;
    dividing by it is the first thing that would break."""
    assert logic.board_pct(0, 100.0) is None
    assert logic.board_pct(0.0, 100.0) is None


# ── Builder ───────────────────────────────────────────────────────────────────

def test_builder_renders_all_twenty_for_an_empty_week(tmp_db):
    """The board never hides itself. A panel that vanishes when empty is a
    panel that gets forgotten."""
    board = logic.build_weekly_board(None, "2026-09-14")

    rows = [r for g in board["groups"] for r in g["rows"]]
    assert len(rows) == 20
    assert all(r["pct"] is None for r in rows)
    assert board["any_data"] is False


def test_builder_computes_pct_from_stored_prices(tmp_db):
    db.upsert_weekly_market_price(None, "2026-09-14", "XLK", 100.0, 100.51)

    board = logic.build_weekly_board(None, "2026-09-14")
    row = [r for g in board["groups"] for r in g["rows"] if r["key"] == "XLK"][0]

    assert round(row["pct"], 2) == 0.51
    assert board["any_data"] is True


def test_builder_keeps_fixed_order_regardless_of_performance(tmp_db):
    """Fixed positions were chosen over ranking so the board reads from muscle
    memory. Storing a big mover must not move its row."""
    db.upsert_weekly_market_price(None, "2026-09-14", "XLRE", 100.0, 140.0)

    board = logic.build_weekly_board(None, "2026-09-14")
    sectors = [r["key"] for g in board["groups"] if g["id"] == "sectors" for r in g["rows"]]

    assert sectors[0] == "XLK"
    assert sectors[-1] == "XLRE"


def test_price_falls_back_to_the_open_until_a_current_is_entered(tmp_db):
    """Spec §"Empty and partial states". On Monday you type the open and nothing
    else; the board must show that number, not a dash, while the percent stays
    blank because there is nothing yet to compare it to."""
    db.upsert_weekly_market_price(None, "2026-09-14", "SPX", 7600.0, None)

    board = logic.build_weekly_board(None, "2026-09-14")
    row = [r for g in board["groups"] for r in g["rows"] if r["key"] == "SPX"][0]

    assert row["price"] == 7600.0
    assert row["pct"] is None


def test_price_prefers_the_current_once_entered(tmp_db):
    db.upsert_weekly_market_price(None, "2026-09-14", "SPX", 7600.0, 7656.98)

    board = logic.build_weekly_board(None, "2026-09-14")
    row = [r for g in board["groups"] for r in g["rows"] if r["key"] == "SPX"][0]

    assert row["price"] == 7656.98


def test_only_indices_and_macro_show_a_price(tmp_db):
    """The screenshot's own split: things with a level vs things with a move."""
    board = logic.build_weekly_board(None, "2026-09-14")
    show = {g["id"]: g["show_price"] for g in board["groups"]}

    assert show == {"indices": True, "sectors": False, "macro": True}


# ── API ───────────────────────────────────────────────────────────────────────

def test_post_saves_a_cell_with_typed_commas(client, tmp_db):
    res = client.post("/api/weekly-board", json={
        "week_start": "2026-09-14", "instrument": "SPX",
        "monday_open": "7,600.00", "current": "7,656.98"})

    assert res.status_code == 200
    stored = db.get_weekly_market_prices(None, "2026-09-14")["SPX"]
    assert stored["monday_open"] == 7600.00
    assert stored["current"] == 7656.98


def test_post_rejects_an_unknown_instrument(client, tmp_db):
    """The instrument list is a closed vocabulary. A typo must not create a
    phantom row that nothing renders and nobody can find."""
    res = client.post("/api/weekly-board", json={
        "week_start": "2026-09-14", "instrument": "XLZ",
        "monday_open": "1", "current": "2"})

    assert res.status_code == 400
    assert db.get_weekly_market_prices(None, "2026-09-14") == {}


def test_post_rejects_a_non_numeric_price(client, tmp_db):
    res = client.post("/api/weekly-board", json={
        "week_start": "2026-09-14", "instrument": "SPX",
        "monday_open": "abc", "current": "2"})

    assert res.status_code == 400
    assert db.get_weekly_market_prices(None, "2026-09-14") == {}


def test_post_rejects_a_non_numeric_second_price(client, tmp_db):
    """Mirror of test_post_rejects_a_non_numeric_price: here the FIRST value
    (monday_open) is valid and the SECOND (current) is junk. This pins that
    both prices are parsed before any write, so a bad second value can't
    leave a half-written row (monday_open saved, current missing)."""
    res = client.post("/api/weekly-board", json={
        "week_start": "2026-09-14", "instrument": "SPX",
        "monday_open": "100", "current": "abc"})

    assert res.status_code == 400
    assert db.get_weekly_market_prices(None, "2026-09-14") == {}


def test_post_requires_a_week(client, tmp_db):
    res = client.post("/api/weekly-board", json={
        "week_start": "", "instrument": "SPX",
        "monday_open": "1", "current": "2"})

    assert res.status_code == 400


def test_weekly_payload_carries_the_board(client, tmp_db):
    db.upsert_weekly_market_price(None, "2026-09-14", "XLK", 100.0, 100.51)

    data = logic.build_weekly_review_data(None, "2026-09-14")

    assert "board" in data
    row = [r for g in data["board"]["groups"] for r in g["rows"] if r["key"] == "XLK"][0]
    assert round(row["pct"], 2) == 0.51


# ── Rendering ─────────────────────────────────────────────────────────────────

def _weekly_html(client, week="2026-09-14"):
    return client.get("/weekly-review?week=" + week).get_data(as_text=True)


def _row_html(html, key):
    """The single wb-row block for one instrument, div-balanced.

    Needed because every empty instrument on the board renders its own
    'class="wb-flat">—' dash — a bare substring check for that class can
    pass against a neighbour's row instead of the row under test.
    """
    marker = 'data-instrument="{}"'.format(key)
    marker_idx = html.index(marker)
    start = html.rfind("<div", 0, marker_idx)
    pos = start
    depth = 0
    while True:
        next_open = html.find("<div", pos)
        next_close = html.find("</div>", pos)
        if next_close == -1:
            raise AssertionError("unclosed wb-row for " + key)
        if next_open != -1 and next_open < next_close:
            depth += 1
            pos = next_open + 4
        else:
            depth -= 1
            pos = next_close + 6
            if depth == 0:
                return html[start:pos]


def test_negative_renders_parenthesised_and_red(client, tmp_db):
    """The accounting convention from the reference board: parentheses for
    negatives, an explicit + for positives. It is why that board reads fast."""
    db.upsert_weekly_market_price(None, "2026-09-14", "XLK", 100.0, 99.20)

    html = _weekly_html(client)

    assert 'class="wb-neg">(0.80%)' in html


def test_positive_renders_signed_and_green(client, tmp_db):
    db.upsert_weekly_market_price(None, "2026-09-14", "XLK", 100.0, 100.51)

    html = _weekly_html(client)

    assert 'class="wb-pos">+0.51%' in html


def test_vix_rising_renders_green_not_bearish_red(client, tmp_db):
    """Deliberate divergence from the internals delta pills, where a rising VIX
    is dark red. The board is a market surface: green means up. Spec §Colour.
    If this test is ever 'fixed' to expect red, read the spec first."""
    db.upsert_weekly_market_price(None, "2026-09-14", "VIX", 15.00, 15.27)

    html = _weekly_html(client)

    assert 'class="wb-pos">+1.80%' in html


def test_empty_week_still_renders_every_instrument(client, tmp_db):
    html = _weekly_html(client)

    assert html.count('class="wb-row"') == 20


def test_open_without_current_shows_the_price_and_a_dash(client, tmp_db):
    db.upsert_weekly_market_price(None, "2026-09-14", "SPX", 7600.0, None)

    html = _weekly_html(client)
    row = _row_html(html, "SPX")

    assert "7,600.00" in html
    assert 'class="wb-flat">—' in row


# ── Entry table ───────────────────────────────────────────────────────────────

def test_editor_renders_two_real_inputs_per_instrument(client, tmp_db):
    """The tab-order invariant. 4.10.0 had to rebuild the internals grid because
    its cells hid their inputs behind a click, and a display:none input is not
    focusable — Tab skipped them. Forty real inputs is what makes the table
    fillable from the keyboard."""
    html = _weekly_html(client)

    editor = html[html.index('id="wb-editor"'):]
    editor = editor[:editor.index("</table>")]
    assert editor.count("<input") == 40


def test_editor_inputs_are_ordered_open_then_current_per_row(client, tmp_db):
    """Tab follows DOM order, so the pairs must be adjacent and in that order —
    open, current, next instrument. Any other order sends the cursor sideways,
    which is the exact complaint that drove the 4.10.0 transpose."""
    import re
    html = _weekly_html(client)
    editor = html[html.index('id="wb-editor"'):]
    editor = editor[:editor.index("</table>")]

    fields = re.findall(r'data-field="(monday_open|current)"', editor)

    assert fields[:4] == ["monday_open", "current", "monday_open", "current"]
    assert len(fields) == 40


def test_editor_cells_are_never_hidden(client, tmp_db):
    """The specific failure mode: a cell that reveals its input on click."""
    html = _weekly_html(client)
    editor = html[html.index('id="wb-editor"'):]
    editor = editor[:editor.index("</table>")]

    assert "display:none" not in editor
    assert "nextElementSibling" not in editor
