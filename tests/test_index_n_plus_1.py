"""F3 — the landing page must not re-fetch every day's trades to compute a
score that no longer uses them.

compute_combined_day_score dropped its execution component (4.9.0) and now
ignores `trades` entirely — it reflects the day's process checklist alone.
The index route still called db.get_trades_for_day(day["id"]) per day before
passing the result in, though. get_trades_for_day opens its own connection
and issues about three queries per trade, so with the real database's 100
days / 241 trades that was ~100 connections and ~800 queries per index load,
every one of them discarded. This module pins the call site so it can't
regress.
"""
import database as db
import app_logic as logic


def test_index_does_not_fetch_trades_per_day(client, tmp_db, monkeypatch):
    day_id_1 = db.upsert_day("2026-09-01", None)
    day_id_2 = db.upsert_day("2026-09-02", None)
    db.insert_trade(day_id_1, 1, "Long", 3, 7756.0, 7795.5, 1035.0, "10:05", "10:40")
    db.insert_trade(day_id_2, 1, "Short", 2, 7800.0, 7780.0, 500.0, "11:00", "11:20")

    calls = []
    real = db.get_trades_for_day

    def spy(day_id):
        calls.append(day_id)
        return real(day_id)

    monkeypatch.setattr(db, "get_trades_for_day", spy)

    res = client.get("/")

    assert res.status_code == 200
    assert calls == [], (
        f"the index route fetched trades for {len(calls)} day(s) — "
        "compute_combined_day_score no longer uses them, so this is a pure N+1"
    )


def test_index_still_computes_a_grade_pct_from_the_day_score_alone(client, tmp_db):
    """The fix must not silently stop populating grade_pct — it just stops
    fetching trades to do it, since compute_combined_day_score never read
    them for anything but a signature-compatibility no-op."""
    import json
    day_id = db.upsert_day("2026-09-01", None)
    db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0, "10:05", "10:40")
    db.update_day_notes(day_id, day_score=json.dumps(
        {"calm": True, "mkt_read": True, "awareness": False, "take_offer": True}))

    res = client.get("/")

    assert res.status_code == 200
    days = db.get_all_days("2000-01-01", "2099-12-31", None)
    day = next(d for d in days if d["id"] == day_id)
    expected = logic.compute_combined_day_score(day.get("day_score", ""))
    assert expected == 75  # 3 of 4 checked
