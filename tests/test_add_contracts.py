"""Adding contracts must extend the working stop, not just the ledger.

Before this, an ADD appended a per-tranche risk stop to the execution row but
created no live_trade_levels row, and _redistribute_stop_qty only ever SHRINKS
levels when open_qty falls. So a 3-contract trade scaled to 6 kept a working
stop covering 3 — and the right panel's net risk, which reads those levels,
reported roughly half the real exposure. A risk panel that under-reports is
worse than no risk panel.
"""
import app_logic as logic
import database as db


def _stop_levels(live_id):
    lt = db.get_live_trade(live_id)
    return [lv for lv in (lt.get("levels") or [])
            if lv["level_type"] == "stop" and (lv["qty"] or 0) > 0]


def _open_trade(qty=3, price=7703.0, stop=7678.0):
    live_id = db.create_live_trade(None, "Long", "MES", price, "05:55", qty, "full")
    db.add_live_trade_execution(live_id, "OPEN", 1, qty, price, "05:55", 0.0,
                                stop_price=stop, stop_source="entered")
    db.set_live_trade_levels(live_id, [{"level_type": "stop", "portion": 1,
                                        "qty": qty, "price": stop}])
    return live_id


def test_add_with_a_stop_creates_a_working_level_for_that_lot(client, tmp_db):
    live_id = _open_trade()

    res = client.post(f"/api/live/{live_id}/add",
                      json={"qty": 3, "price": 7705.0, "time": "06:01",
                            "stop_price": 7685.0})
    assert res.status_code == 200

    levels = _stop_levels(live_id)
    assert sum(lv["qty"] for lv in levels) == 6, (
        "working stops must cover every open contract, not just the original lot")
    assert sorted(lv["price"] for lv in levels) == [7678.0, 7685.0]


def test_add_without_a_stop_still_creates_a_level_at_the_default(client, tmp_db):
    """The common case. Leaving the gap open when the field is skipped would
    preserve the bug for most adds."""
    live_id = _open_trade()

    client.post(f"/api/live/{live_id}/add",
                json={"qty": 3, "price": 7705.0, "time": "06:01"})

    levels = _stop_levels(live_id)
    assert sum(lv["qty"] for lv in levels) == 6
    # 20-pt default, direction-aware: long -> price - 20
    assert 7685.0 in [lv["price"] for lv in levels]


def test_the_added_level_matches_the_ledger_stop_for_that_tranche(client, tmp_db):
    """The working stop and the per-tranche risk stop must agree — they are the
    same decision recorded twice, and a divergence is unexplainable on screen."""
    live_id = _open_trade()
    client.post(f"/api/live/{live_id}/add",
                json={"qty": 2, "price": 7710.0, "time": "06:05",
                      "stop_price": 7690.0})

    lt = db.get_live_trade(live_id)
    add_exec = [e for e in lt["executions"] if e["exec_type"] == "ADD"][0]
    prices = [lv["price"] for lv in _stop_levels(live_id)]
    assert add_exec["stop_price"] == 7690.0
    assert 7690.0 in prices


def test_add_carries_the_target_onto_the_execution(client, tmp_db):
    live_id = _open_trade()
    client.post(f"/api/live/{live_id}/add",
                json={"qty": 3, "price": 7705.0, "time": "06:01",
                      "stop_price": 7685.0, "target_price": 7760.0})

    lt = db.get_live_trade(live_id)
    add_exec = [e for e in lt["executions"] if e["exec_type"] == "ADD"][0]
    assert add_exec["target_price"] == 7760.0
    assert add_exec["target_source"] == "entered"


def test_a_later_exit_still_redistributes_the_stops(client, tmp_db):
    """The new level must not break the existing shrink-on-exit behaviour."""
    live_id = _open_trade()
    client.post(f"/api/live/{live_id}/add",
                json={"qty": 3, "price": 7705.0, "time": "06:01",
                      "stop_price": 7685.0})
    assert sum(lv["qty"] for lv in _stop_levels(live_id)) == 6

    db.add_live_trade_execution(live_id, "EXIT", 1, 2, 7720.0, "06:30", 0.0)
    db.recalculate_position(live_id)

    assert sum(lv["qty"] for lv in _stop_levels(live_id)) == 4, (
        "stops must shrink to the remaining open qty after an exit")


def test_two_adds_each_get_their_own_level(client, tmp_db):
    live_id = _open_trade()
    client.post(f"/api/live/{live_id}/add",
                json={"qty": 1, "price": 7705.0, "time": "06:01", "stop_price": 7685.0})
    client.post(f"/api/live/{live_id}/add",
                json={"qty": 2, "price": 7712.0, "time": "06:10", "stop_price": 7692.0})

    levels = _stop_levels(live_id)
    assert sum(lv["qty"] for lv in levels) == 6
    assert sorted(lv["price"] for lv in levels) == [7678.0, 7685.0, 7692.0]


def test_the_add_tray_actually_renders_stop_and_target_inputs(client, tmp_db):
    """The bug that started this: a form WITH stop and target existed but was
    never called, while the one on screen had neither. Asserting on rendered
    output is the only thing that distinguishes those two states — the dead
    form's markup looked perfectly correct in the source.
    """
    html = client.get("/live-v2").get_data(as_text=True)

    assert 'id="poc-banner-add-stop"' in html
    assert 'id="poc-banner-add-target"' in html
    assert 'id="poc-banner-add-risk"' in html


def test_the_abandoned_add_form_is_gone(client, tmp_db):
    """It shipped stop and target fields nobody could reach. Keeping it would
    leave two forms for one job and invite the next edit into the wrong one."""
    html = client.get("/live-v2").get_data(as_text=True)

    for dead in ("buildAddContractsForm", "dynSubmitAdd",
                 "dynToggleAddForm", "dyn-add-stop"):
        assert dead not in html, f"{dead} should have been removed"
