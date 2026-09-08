"""Entry emotion on the assessment page.

The assessment page runs before the live trade exists, so the trader's pick
is first saved on `trade_strength`. The trade is created afterwards carrying
a `strength_id`, and the weekly analytics read `emotion_entry` off
`live_trades`/`trades` directly (they GROUP BY column, not by joining through
strength) — so `POST /api/live` must copy the value across at creation time.
"""
import database as db


def _cols(table):
    with db.get_conn() as conn:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def test_trade_strength_has_emotion_entry_column(tmp_db):
    assert "emotion_entry" in _cols("trade_strength")


def test_trade_strength_migration_is_rerunnable(tmp_db):
    db.init_db()
    db.init_db()
    assert _cols("trade_strength").count("emotion_entry") == 1


def test_create_trade_strength_accepts_emotion_entry(tmp_db):
    sid = db.create_trade_strength(
        context_id=None, account_id=None, value=1, volume=1, trend=1,
        mental_state="calm", confidence="medium", adh=1,
        patience=1, arrival_context=1, confirmation=1,
        emotion_entry="greed",
    )
    row = db.get_trade_strength(sid)
    assert row["emotion_entry"] == "greed"


def test_create_trade_strength_emotion_entry_defaults_to_none(tmp_db):
    """Backward-compatible signature: existing callers that omit the kwarg
    must not break."""
    sid = db.create_trade_strength(
        context_id=None, account_id=None, value=0, volume=0, trend=0,
        mental_state="calm", confidence="medium",
    )
    row = db.get_trade_strength(sid)
    assert row["emotion_entry"] is None


def test_get_trade_strength_returns_none_for_missing_id(tmp_db):
    assert db.get_trade_strength(999999) is None


def test_post_trade_strength_accepts_emotion_entry(client, tmp_db):
    res = client.post("/api/trade-strength", json={
        "value": 1, "volume": 1, "trend": 1, "adh": 1,
        "confidence": "high", "patience": 1, "arrival_context": 1,
        "confirmation": 1, "emotion_entry": "impatience",
    })
    assert res.status_code == 200
    data = res.get_json()
    row = db.get_trade_strength(data["id"])
    assert row["emotion_entry"] == "impatience"


def test_post_live_trade_copies_emotion_entry_from_strength(client, tmp_db):
    sid = db.create_trade_strength(
        context_id=None, account_id=None, value=1, volume=1, trend=1,
        mental_state="calm", confidence="medium",
        emotion_entry="overconfidence",
    )
    res = client.post("/api/live", json={
        "direction": "Long", "instrument": "MES", "entry_price": 7756.0,
        "entry_time": "10:05", "total_qty": 3, "mode": "full",
        "strength_id": sid,
    })
    assert res.status_code == 200
    live_id = res.get_json()["id"]
    lt = db.get_live_trade(live_id)
    assert lt["emotion_entry"] == "overconfidence"


def test_post_live_trade_without_strength_id_leaves_emotion_entry_null(client, tmp_db):
    res = client.post("/api/live", json={
        "direction": "Long", "instrument": "MES", "entry_price": 7756.0,
        "entry_time": "10:05", "total_qty": 3, "mode": "full",
    })
    assert res.status_code == 200
    live_id = res.get_json()["id"]
    lt = db.get_live_trade(live_id)
    assert lt["emotion_entry"] is None


def test_post_live_trade_with_strength_missing_emotion_entry_leaves_null(client, tmp_db):
    """A strength row saved before this feature (or without a pick) has no
    emotion_entry — the copy must not raise or invent a value."""
    sid = db.create_trade_strength(
        context_id=None, account_id=None, value=1, volume=1, trend=1,
        mental_state="calm", confidence="medium",
    )
    res = client.post("/api/live", json={
        "direction": "Long", "instrument": "MES", "entry_price": 7756.0,
        "entry_time": "10:05", "total_qty": 3, "mode": "full",
        "strength_id": sid,
    })
    assert res.status_code == 200
    live_id = res.get_json()["id"]
    lt = db.get_live_trade(live_id)
    assert lt["emotion_entry"] is None
