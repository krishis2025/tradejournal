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
