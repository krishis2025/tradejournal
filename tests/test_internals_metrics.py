"""Market Internals: the /CL and TNX columns that replaced $TRIN in the UI.

$TRIN's column deliberately stays in the table. It holds recorded history and
SQLite column drops are disruptive for no gain, so it is dropped from the two
templates only — these tests pin that the old data still reads back.
"""
import sqlite3

import database as db


def test_cl_and_tnx_columns_exist_after_init(tmp_db):
    cols = {r[1] for r in sqlite3.connect(tmp_db)
            .execute("PRAGMA table_info(market_internals)").fetchall()}

    assert "cl" in cols, "/CL has no column to store into"
    assert "tnx" in cols, "TNX has no column to store into"


def test_upsert_round_trips_the_new_metrics(tmp_db):
    """upsert_internals filters against INTERNALS_FIELDS, so a column that
    exists but is missing from that allowlist is silently discarded — the
    write appears to succeed and the value never lands."""
    day = db.upsert_day("2026-09-14", None)

    db.upsert_internals(day, "morning", cl="62.40", tnx="4.12", vix="17.48")

    row = db.get_internals_for_day(day)[0]
    assert row["cl"] == "62.40"
    assert row["tnx"] == "4.12"
    assert row["vix"] == "17.48"


def test_existing_trin_data_survives(tmp_db):
    """The UI stops showing $TRIN; the journal must not lose what it recorded."""
    day = db.upsert_day("2026-09-14", None)
    db.upsert_internals(day, "morning", trin="0.87")

    db.init_db()  # runs on every request, so it must be safe over real data

    assert db.get_internals_for_day(day)[0]["trin"] == "0.87"


# ── Template guards ───────────────────────────────────────────────────────────
# Both internals grids are built in JavaScript, so these assert on the served
# source, not on rendered DOM. That is weaker than a markup assertion and cannot
# prove the table looks right — it can only pin the two structural properties
# that silently break the feature. Colour and layout need human eyes.

def _internals_sources(client, day_id):
    return {
        "internals_v2": client.get(f"/day/{day_id}/internals-v2").get_data(as_text=True),
        "live_v2": client.get("/live-v2").get_data(as_text=True),
    }


def test_no_metric_cell_hides_its_input(client, tmp_db, day_id):
    """The tab-order invariant, and the whole point of the transpose.

    Vol% and ADH used to render the value as a pill with the real input inside a
    `display:none` sibling, revealed on click. A hidden input is not focusable,
    so Tab skipped both cells — transposing the table alone would not have made
    a session row keyboard-fillable. If that pattern comes back, so does the bug.
    """
    # The signature is the pill's click-swap: hide the span, reveal the sibling,
    # focus the input inside it. Matching on a bare `display:none` would be
    # wrong — the sector modal and the review file input use it legitimately.
    swap = "nextElementSibling.querySelector('input').focus()"
    for name, html in _internals_sources(client, day_id).items():
        assert swap not in html, (
            f"{name}: a metric cell reveals its input on click again, so the "
            "input is display:none until then and Tab skips the cell")


def test_vitals_columns_are_metrics_including_cl_and_tnx(client, tmp_db, day_id):
    for name, html in _internals_sources(client, day_id).items():
        assert "'/CL'" in html, f"{name}: /CL is not among the vitals columns"
        assert "'TNX'" in html, f"{name}: TNX is not among the vitals columns"
        assert "$TRIN" not in html, f"{name}: $TRIN is still rendered"


def test_client_state_still_carries_trin(client, tmp_db, day_id):
    """Data-safety guard, not cosmetics.

    internals_v2 hydrates only the keys already present in its state defaults,
    and saveSession POSTs that whole object into an INSERT OR REPLACE. Drop
    `trin` from the defaults and the next save writes '' over every recorded
    value — 115 rows in the real journal at the time this was written.
    """
    html = client.get(f"/day/{day_id}/internals-v2").get_data(as_text=True)

    assert "trin:''" in html, (
        "internals_v2 dropped `trin` from its client state — the next session "
        "save will blank the stored $TRIN history")
