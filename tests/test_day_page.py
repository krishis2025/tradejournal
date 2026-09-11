"""Day page rendering — guards the tag-panel routing bug.

day.html used to split its tag panels by list position
(tag_groups[:4] / tag_groups[4:]). Removing a group from TAG_GROUPS shifted
that split, so the dedicated three-column pre-trade panel silently stopped
rendering while the page still returned 200 — a status-code check alone
would never have caught it. The template now selects panels by group id;
this test pins that down.
"""
import database as db


def test_day_page_renders_the_pre_trade_tag_panel(client, tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, 50.0, "10:00", "10:30")
    db.set_trade_tags(trade_id, "pre", ["Trade came to me"])

    res = client.get(f"/day/{day_id}")

    assert res.status_code == 200
    html = res.get_data(as_text=True)
    # These assert on MARKUP, not on strings that also appear in the page's
    # <style> block (`.tag-panel-3 { ... }`, `.tag-btn.active-pre-good { ... }`
    # both match a bare substring check regardless of whether the panel ever
    # renders a single tag). A real container div and a real button class
    # attribute are the only things that prove the panel rendered.
    assert '<div class="tag-panel-3">' in html, (
        "the dedicated pre-trade panel container div is missing from the markup"
    )
    assert 'class="tag-btn active-pre-good"' in html, (
        "the pre-trade panel's seeded tag never rendered as a tag-btn with its "
        "active class — the panel container is present but empty"
    )


def test_entry_form_puts_qty_above_price(client, tmp_db):
    """Cosmetic ordering, pinned so a later edit cannot silently swap it back.

    Nothing reads DOM order — efUpdateRisk and handleEnterClick fetch by id —
    so only a test can catch a regression here.
    """
    res = client.get("/live-v2")

    assert res.status_code == 200
    html = res.get_data(as_text=True)
    qty_at = html.index('id="ef-qty"')
    price_at = html.index('id="ef-price"')
    assert qty_at < price_at, "Qty must render above Price in the entry form"


def test_entry_form_focuses_qty_on_render(client, tmp_db):
    """The form is injected via innerHTML, so the autofocus attribute would
    never fire — an explicit focus() call is required."""
    html = client.get("/live-v2").get_data(as_text=True)

    assert "qtyInput.focus()" in html


def _day_above_the_plan_check_floor():
    """PLAN CHECK ignores trades before `plan_check_from_date` — they predate
    planned-exit capture. The shared `day_id` fixture is 2026-09-01, below that
    floor, so these tests need a day of their own or the strip renders nothing.
    """
    import app_logic as logic
    date = logic.get_plan_check_from_date()
    return date, db.upsert_day(date, None)


def _grid_cells(block):
    """Direct children of one PLAN CHECK grid row.

    Counts by indent depth so the spans nested inside `.pc-tail` — which share
    a single track — are not miscounted as columns of their own.
    """
    import re
    return len(re.findall(r"^        <(?:span|input)\b", block, flags=re.M))


def _plan_check_blocks(html):
    def block(marker):
        b = html[html.index(marker):]
        return b[:b.index("\n      </div>")]
    return block('pc-row pc-grid pc-head'), block('pc-row pc-grid" data-trade')


def test_plan_check_header_and_rows_share_one_grid(client, tmp_db):
    """The real invariant behind this strip.

    It used to be display:flex, which sizes every cell to its own content — so a
    header reading "stop" and a value reading "7618.25" could never line up. The
    fix is one shared track list, and the way it silently breaks again is a
    column added to one side and not the other, which shifts every later heading
    off its values. Only checking all three counts together catches that from
    either direction.
    """
    import re
    date, day = _day_above_the_plan_check_floor()
    db.insert_trade(day, 1, "Long", 1, 7700.0, 7710.0, 50.0, "10:00", "10:30")

    html = client.get(f"/day/{day}").get_data(as_text=True)

    tracks = re.search(r"\.pc-grid \{ grid-template-columns:\s*([^;]+);", html, re.S)
    assert tracks, "the shared .pc-grid track list is missing"
    columns = len(tracks.group(1).split())
    head, row = _plan_check_blocks(html)

    assert head.count("<span") == columns, (
        f"the header declares {head.count('<span')} cells against {columns} grid "
        "columns — headings no longer line up with values")
    assert _grid_cells(row) == columns, (
        f"a row places {_grid_cells(row)} cells into {columns} grid columns — "
        "too few shifts the values, too many wraps onto a second line")


def test_plan_check_row_shows_entry_exit_times_and_pnl(client, tmp_db):
    """Without these the strip was four bare prices with no way to tell which
    trade a row was, or whether it won.

    Every assertion is scoped to the row block: entry and exit times also appear
    in the trade tray further down the page, so a page-wide substring check
    passes even when the strip's own cells are gone.
    """
    import app_logic as logic
    date, day = _day_above_the_plan_check_floor()
    db.insert_trade(day, 1, "Long", 1, 7700.0, 7710.0, 50.0, "10:00", "10:30")

    logic_row = logic.build_plan_check(date, None)["today"][0]
    assert logic_row["entry_time"] == "10:00"
    assert logic_row["exit_time"] == "10:30"
    assert logic_row["pnl"] == 50.0

    _, row = _plan_check_blocks(client.get(f"/day/{day}").get_data(as_text=True))

    assert 'pc-time">10:00<' in row, "the strip's own entry-time cell is missing"
    assert 'pc-time">10:30<' in row, "the strip's own exit-time cell is missing"
    assert 'pc-pnl pos">+50<' in row, "a winning P&L must render green and signed"
