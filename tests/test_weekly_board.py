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
