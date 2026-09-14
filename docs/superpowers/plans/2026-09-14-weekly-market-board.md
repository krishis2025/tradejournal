# Weekly Market Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a 20-instrument market board on the weekly review page showing each instrument's percent move from Monday's open, with an inline table for entering the two prices.

**Architecture:** One new table holding two nullable prices per instrument per week; the percent is computed on read, never stored. The instrument list is an ordered constant in `app_logic`, so display order is fixed and independent of what rows exist. The board and its entry table are server-rendered Jinja on the existing weekly page; only the autosave is JavaScript.

**Tech Stack:** Python 3.9.6, Flask, SQLite (stdlib `sqlite3`), Jinja2, vanilla JS. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-14-weekly-market-board-design.md`

## Global Constraints

- **Python 3.9.6.** No 3.10+ syntax — no `match`, no `X | Y` type unions.
- **Three-layer rule.** SQL only in `database.py`; business logic only in `app_logic.py`; `server.py` holds routes only.
- **`init_db()` runs on every request** via `@app.before_request`. Every migration must be guarded and re-runnable forever.
- **Nothing derived is persisted.** The percent is computed on read.
- **`data/journal.db` is gitignored** and never travels with the code. Schema changes must land through `init_db()`.
- **Update `SCHEMA.md` whenever the DB schema changes.**
- **Colour rule: green for up, red for down, for every instrument including VIX, TNX and CL.** This deliberately differs from the internals delta pills in 4.10.0. Do not "fix" the inconsistency in either direction. Spec §Colour explains why.
- **Fixed instrument order.** Never sort the board by performance.
- **`instrument` stores the stable key** (`XLK`, `SPX`, `TLT`), never the display label.
- **This feature touches the weekly page only.** Do not mirror anything into `internals_v2.html` or `live_v2.html`, and do not add SMH to the internals sector vocabulary.
- **Commit straight to main. Never branch, never open a PR. COMMIT ONLY — do not push to any remote.**
- **Every new test must be mutation-checked**: reintroduce the bug it guards, watch that specific test fail, restore. A test that passes with the bug present is worse than no test. State the result in the task report.

---

### Task 1: Table, migration, and the database layer

**Files:**
- Modify: `database.py` (migration block beside the other `CREATE TABLE IF NOT EXISTS` statements in `init_db()`; functions near `get_or_create_weekly_review`, around line 3110)
- Modify: `SCHEMA.md`
- Test: `tests/test_weekly_board.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `db.get_weekly_market_prices(account_id, week_start) -> dict` keyed by instrument, each value `{"monday_open": float|None, "current": float|None}`
  - `db.upsert_weekly_market_price(account_id, week_start, instrument, monday_open, current) -> None`

**Critical detail:** `weekly_market_prices` carries its own `account_id` column and does **not** join `trading_days`. The existing `_account_scope_where()` helper writes `d.account_id = ?` and will produce broken SQL here. Scope the account explicitly, handling the legacy `NULL` account, exactly as `get_or_create_weekly_review` does.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_weekly_board.py`:

```python
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
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m pytest tests/test_weekly_board.py -q`
Expected: FAIL — `sqlite3.OperationalError: no such table: weekly_market_prices`, and `AttributeError` on the two `db.` functions.

Check `db.create_account` exists with that signature before relying on it: `grep -n "def create_account" database.py`. If it differs, adapt the fixture call in `test_accounts_are_isolated` only — do not change the other tests.

- [ ] **Step 3: Add the migration**

In `database.py`, inside `init_db()`, beside the other `CREATE TABLE IF NOT EXISTS` blocks:

```python
        # Migration: weekly market board — two typed prices per instrument per
        # week. The percent is computed on read; nothing derived is stored.
        # `instrument` holds the stable key ('XLK', 'SPX', 'TLT'), never the
        # display label, so relabelling on screen cannot orphan a row.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS weekly_market_prices (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id  INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
                week_start  TEXT NOT NULL,
                instrument  TEXT NOT NULL,
                monday_open REAL,
                current     REAL,
                updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                UNIQUE(account_id, week_start, instrument)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wmp_week "
                     "ON weekly_market_prices(account_id, week_start)")
```

- [ ] **Step 4: Add the two functions**

In `database.py`, near `get_or_create_weekly_review`:

```python
# ── Weekly market board ──────────────────────────────────────────────────────
# This table carries its own account_id and does NOT join trading_days, so
# _account_scope_where() does not apply — it emits `d.account_id`. Scope the
# account explicitly here, including the legacy NULL-account case.

def get_weekly_market_prices(account_id, week_start):
    """{instrument: {'monday_open': float|None, 'current': float|None}}."""
    aid = int(account_id) if account_id else None
    with get_conn() as conn:
        if aid is None:
            rows = conn.execute(
                "SELECT instrument, monday_open, current FROM weekly_market_prices "
                "WHERE account_id IS NULL AND week_start = ?", (week_start,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT instrument, monday_open, current FROM weekly_market_prices "
                "WHERE account_id = ? AND week_start = ?", (aid, week_start)
            ).fetchall()
        return {r["instrument"]: {"monday_open": r["monday_open"],
                                  "current": r["current"]} for r in rows}


def upsert_weekly_market_price(account_id, week_start, instrument, monday_open, current):
    """Write one cell pair. UNIQUE(account_id, week_start, instrument) makes a
    repeat write an update, so a mid-week refresh replaces rather than stacks."""
    aid = int(account_id) if account_id else None
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO weekly_market_prices
                (account_id, week_start, instrument, monday_open, current, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now','localtime'))
            ON CONFLICT(account_id, week_start, instrument) DO UPDATE SET
                monday_open = excluded.monday_open,
                current     = excluded.current,
                updated_at  = excluded.updated_at
        """, (aid, week_start, instrument, monday_open, current))
```

Note on `ON CONFLICT`: SQLite supports upsert from 3.24 (2018). Confirm with
`python3 -c "import sqlite3; print(sqlite3.sqlite_version)"`. If it reports older than 3.24, replace the statement with a `DELETE` + `INSERT` inside the same `with get_conn()` block and say so in the report.

**`UNIQUE` with a NULL column:** SQLite treats NULLs as distinct in a UNIQUE index, so `ON CONFLICT` will NOT fire for the legacy `account_id IS NULL` rows — every write would insert a duplicate. `test_upsert_replaces_rather_than_duplicating` uses `None` precisely to catch this. If it fails on the count assertion, fix it by branching: for `aid is None`, `UPDATE` first and `INSERT` only when `cursor.rowcount == 0`. Do not "fix" it by changing the test to use a real account.

- [ ] **Step 5: Run the tests and watch them pass**

Run: `python3 -m pytest tests/test_weekly_board.py -q`
Expected: 6 passed.

- [ ] **Step 6: Mutation-check the two load-bearing tests**

For each, make the change, run, confirm the named test fails, then restore:

1. Drop `UNIQUE(account_id, week_start, instrument)` from the `CREATE TABLE` and delete the test DB → `test_upsert_replaces_rather_than_duplicating` must fail on the count.
2. In `get_weekly_market_prices`, remove `AND week_start = ?` and its param → `test_weeks_are_isolated` must fail.

Record both results in the report. If either passes with the bug present, the test is wrong — fix the test, not the mutation.

- [ ] **Step 7: Update SCHEMA.md**

Add a numbered section matching the file's existing style, after the last table:

```markdown
### 30. WEEKLY_MARKET_PRICES

| Column       | Type    | Constraints                                       |
|--------------|---------|---------------------------------------------------|
| id           | INTEGER | PK AUTOINCREMENT                                  |
| account_id   | INTEGER | FK → accounts(id) ON DELETE CASCADE, nullable     |
| week_start   | TEXT    | NOT NULL, Monday ISO (YYYY-MM-DD)                 |
| instrument   | TEXT    | NOT NULL, stable key ('XLK', 'SPX', 'TLT')        |
| monday_open  | REAL    | nullable until entered                            |
| current      | REAL    | nullable until entered                            |
| updated_at   | TEXT    | NOT NULL DEFAULT (datetime('now','localtime'))    |

**Unique:** (account_id, week_start, instrument)

Two typed prices per instrument per week, backing the weekly market board. The
percent move is computed on read and never stored. `instrument` holds the stable
key, never the display label, so relabelling on screen cannot orphan a row. The
ordered instrument list lives in `app_logic.WEEKLY_BOARD`.
```

Renumber only if `30` collides — check the last section number first with
`grep -n "^### [0-9]" SCHEMA.md | tail -1`.

- [ ] **Step 8: Commit**

```bash
git add database.py SCHEMA.md tests/test_weekly_board.py
git commit -m "feat: weekly market board storage"
```

---

### Task 2: Instrument list, price parsing, and the board builder

**Files:**
- Modify: `app_logic.py` (add near the other vocabularies, e.g. beside `GRADES`)
- Test: `tests/test_weekly_board.py` (append)

**Interfaces:**
- Consumes: `db.get_weekly_market_prices(account_id, week_start)` from Task 1.
- Produces:
  - `logic.WEEKLY_BOARD` — ordered tuple of `(key, label, group)` triples, 20 entries
  - `logic.board_keys() -> set` of valid instrument keys
  - `logic.parse_price(raw) -> float|None` — raises `ValueError` on junk
  - `logic.board_pct(monday_open, current) -> float|None`
  - `logic.build_weekly_board(account_id, week_start) -> dict` shaped
    `{"groups": [{"id","label","show_price","rows":[…]}], "any_data": bool}`
    where each row is `{"key","label","monday_open","current","pct"}`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_weekly_board.py`:

```python
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


def test_only_indices_and_macro_show_a_price(tmp_db):
    """The screenshot's own split: things with a level vs things with a move."""
    board = logic.build_weekly_board(None, "2026-09-14")
    show = {g["id"]: g["show_price"] for g in board["groups"]}

    assert show == {"indices": True, "sectors": False, "macro": True}
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m pytest tests/test_weekly_board.py -q`
Expected: the new tests FAIL with `AttributeError: module 'app_logic' has no attribute 'WEEKLY_BOARD'`. The six from Task 1 still pass.

- [ ] **Step 3: Add the constant and helpers**

In `app_logic.py`, near the other vocabularies:

```python
# ── Weekly market board ──────────────────────────────────────────────────────
# Fixed order, never sorted by performance: stable positions were chosen
# deliberately so the board can be read from muscle memory week to week.
# The key is stable and stored; the label is display-only and may change.
# SMH is not a GICS sector — it sits in the sectors group by request, directly
# after Tech.

WEEKLY_BOARD = (
    ("SPX",  "S&P 500",      "indices"),
    ("NDX",  "Nasdaq 100",   "indices"),
    ("RUT",  "Russell 2000", "indices"),

    ("XLK",  "Tech",    "sectors"),
    ("SMH",  "SMH",     "sectors"),
    ("XLF",  "Fin",     "sectors"),
    ("XLC",  "Comm",    "sectors"),
    ("XLY",  "Disc",    "sectors"),
    ("XLI",  "Indust",  "sectors"),
    ("XLV",  "Health",  "sectors"),
    ("XLP",  "Staples", "sectors"),
    ("XLE",  "Energy",  "sectors"),
    ("XLU",  "Utils",   "sectors"),
    ("XLB",  "Matls",   "sectors"),
    ("XLRE", "RE",      "sectors"),

    ("TLT",  "BONDS",      "macro"),
    ("TNX",  "10YR YIELD", "macro"),
    ("VIX",  "VIX",        "macro"),
    ("GC",   "GOLD",       "macro"),
    ("CL",   "OIL",        "macro"),
)

# Indices and macro carry a price and a percent; sectors carry only a move.
BOARD_GROUPS = (
    ("indices", "INDICES", True),
    ("sectors", "SECTORS", False),
    ("macro",   "MACRO",   True),
)


def board_keys():
    return {k for k, _, _ in WEEKLY_BOARD}


def parse_price(raw):
    """Coerce a typed price to float, or None when blank.

    Accepts the thousands separators that actually get typed ('7,656.98'),
    which bare float() rejects. Raises ValueError on anything else, including
    'nan' and 'inf' — both survive float() and would silently poison every
    percent computed from them.
    """
    import math
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "")
    if s == "":
        return None
    value = float(s)          # raises ValueError on junk
    if not math.isfinite(value):
        raise ValueError("not a finite number: {!r}".format(raw))
    return value


def board_pct(monday_open, current):
    """Percent move from Monday's open, or None when it cannot be computed.

    A missing open is the normal state of every instrument at the start of a
    week, so the zero/None guard is the common path, not an edge case.
    """
    if monday_open is None or current is None or monday_open == 0:
        return None
    return (current - monday_open) / monday_open * 100.0


def build_weekly_board(account_id, week_start):
    """Ordered board for one week. All twenty instruments always render."""
    stored = db.get_weekly_market_prices(account_id, week_start)
    groups = []
    any_data = False
    for gid, glabel, show_price in BOARD_GROUPS:
        rows = []
        for key, label, group in WEEKLY_BOARD:
            if group != gid:
                continue
            cell = stored.get(key) or {}
            mo, cur = cell.get("monday_open"), cell.get("current")
            if mo is not None or cur is not None:
                any_data = True
            rows.append({"key": key, "label": label,
                         "monday_open": mo, "current": cur,
                         "pct": board_pct(mo, cur)})
        groups.append({"id": gid, "label": glabel,
                       "show_price": show_price, "rows": rows})
    return {"groups": groups, "any_data": any_data}
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `python3 -m pytest tests/test_weekly_board.py -q`
Expected: 18 passed.

- [ ] **Step 5: Mutation-check three tests**

Make each change, run, confirm the named test fails, restore:

1. Remove the `math.isfinite` guard from `parse_price` → `test_parse_price_rejects_junk_and_non_finite` must fail.
2. Change `monday_open == 0` to `monday_open is None` in `board_pct` → `test_pct_is_none_when_the_open_is_zero` must fail with `ZeroDivisionError`.
3. Sort `rows` by `pct` before appending in `build_weekly_board` → `test_builder_keeps_fixed_order_regardless_of_performance` must fail.

Record all three in the report.

- [ ] **Step 6: Run the whole suite and commit**

```bash
python3 -m pytest tests/ -q
git add app_logic.py tests/test_weekly_board.py
git commit -m "feat: weekly board instrument list, price parsing, and builder"
```

---

### Task 3: API route and page wiring

**Files:**
- Modify: `server.py` (add beside `api_save_weekly_review`, around line 1975)
- Modify: `app_logic.py` (`build_weekly_review_data`, around line 2720)
- Test: `tests/test_weekly_board.py` (append)

**Interfaces:**
- Consumes: `logic.build_weekly_board`, `logic.parse_price`, `logic.board_keys`, `db.upsert_weekly_market_price` from Tasks 1–2.
- Produces:
  - `POST /api/weekly-board` accepting `{week_start, instrument, monday_open, current}`
  - `data["board"]` on the weekly-review payload, so the page and `GET /api/weekly-review` both carry it

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_weekly_board.py`:

```python
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
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m pytest tests/test_weekly_board.py -q`
Expected: the five new tests FAIL — 404 on the route, and `KeyError: 'board'`.

- [ ] **Step 3: Add the route**

In `server.py`, beside `api_save_weekly_review`:

```python
@app.route("/api/weekly-board", methods=["POST"])
def api_save_weekly_board():
    account_id = request.args.get("account") or None
    body = request.get_json(silent=True) or {}
    week = (body.get("week_start") or "").strip()
    instrument = (body.get("instrument") or "").strip()
    if not week:
        return jsonify({"error": "week_start is required"}), 400
    if instrument not in logic.board_keys():
        return jsonify({"error": "unknown instrument"}), 400
    try:
        monday_open = logic.parse_price(body.get("monday_open"))
        current = logic.parse_price(body.get("current"))
    except ValueError:
        return jsonify({"error": "prices must be numbers"}), 400
    db.upsert_weekly_market_price(account_id, week, instrument, monday_open, current)
    return jsonify({"ok": True})
```

- [ ] **Step 4: Wire the board onto the payload**

In `app_logic.build_weekly_review_data`, beside the other assembled sections, add:

```python
    board = build_weekly_board(account_id, mon)
```

and include `"board": board,` in the returned dict. Find the existing `return {` in that function and add the key alongside the others — do not restructure the return.

- [ ] **Step 5: Run the tests and watch them pass**

Run: `python3 -m pytest tests/test_weekly_board.py -q`
Expected: 23 passed.

- [ ] **Step 6: Mutation-check the vocabulary guard**

Change `if instrument not in logic.board_keys():` to `if not instrument:` → `test_post_rejects_an_unknown_instrument` must fail. Restore. Record it.

- [ ] **Step 7: Run the whole suite and commit**

```bash
python3 -m pytest tests/ -q
git add server.py app_logic.py tests/test_weekly_board.py
git commit -m "feat: weekly board API and page wiring"
```

---

### Task 4: The board display

**Files:**
- Modify: `templates/weekly_review.html` (macros near the top beside `money`, around line 4; markup inside `{% block content %}` after the `wr-kpis` div, around line 245; CSS in the page's existing `<style>` block)
- Test: `tests/test_weekly_board.py` (append)

**Interfaces:**
- Consumes: `data.board` from Task 3.
- Produces: rendered markup carrying classes `wb-pos`, `wb-neg`, `wb-flat`, and a container `wb-board`.

**Layout:** four columns — INDICES (3 rows), then SECTORS across two columns of six, then MACRO (5 rows). Indices and macro rows show the price above the percent; sector rows show the percent only. Collapse to two columns then one on narrow screens.

**Icons:** inline SVG, monoline, matching the existing internals icons. One per instrument. Keep them small (14–16px) and give them `stroke="currentColor"` so they inherit the row colour.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_weekly_board.py`:

```python
# ── Rendering ─────────────────────────────────────────────────────────────────

def _weekly_html(client, week="2026-09-14"):
    return client.get("/weekly-review?week=" + week).get_data(as_text=True)


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

    assert "7,600.00" in html
    assert 'class="wb-flat">—' in html
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m pytest tests/test_weekly_board.py -q`
Expected: the five new tests FAIL — none of the `wb-` classes exist yet.

- [ ] **Step 3: Add the formatting macros**

In `templates/weekly_review.html`, beside the existing `money` macro:

```jinja
{% macro wb_pct(v) -%}
{%- if v is none -%}<span class="wb-flat">—</span>
{%- elif v < 0 -%}<span class="wb-neg">({{ '{:.2f}'.format(v|abs) }}%)</span>
{%- else -%}<span class="wb-pos">+{{ '{:.2f}'.format(v) }}%</span>
{%- endif -%}
{%- endmacro %}

{% macro wb_price(v) -%}
{%- if v is none -%}<span class="wb-flat">—</span>
{%- else -%}{{ '{:,.2f}'.format(v) }}
{%- endif -%}
{%- endmacro %}
```

- [ ] **Step 4: Add the markup**

Inside `{% block content %}`, after the `wr-kpis` div:

```jinja
  <!-- Market board — see docs/superpowers/specs/2026-09-14-weekly-market-board-design.md -->
  <div class="wb-board">
    <div class="wb-board-head">
      <span class="wb-board-title">MARKET — {{ data.week_label }}</span>
      <button type="button" class="wb-edit-btn" onclick="wbToggleEditor()">Edit values</button>
    </div>
    <div class="wb-cols">
      {% for g in data.board.groups %}
      <div class="wb-group wb-group-{{ g.id }}">
        <div class="wb-group-label">{{ g.label }}</div>
        <div class="wb-group-rows">
          {% for r in g.rows %}
          <div class="wb-row" data-instrument="{{ r.key }}">
            <div class="wb-name">{{ r.label }}</div>
            {% if g.show_price %}<div class="wb-price">{{ wb_price(r.current) }}</div>{% endif %}
            <div class="wb-move">{{ wb_pct(r.pct) }}</div>
          </div>
          {% endfor %}
        </div>
      </div>
      {% endfor %}
    </div>
  </div>
```

The sectors group splits into two columns of six via CSS (`column-count: 2` on `.wb-group-sectors .wb-group-rows`), not by slicing the row list in Jinja — slicing would hard-code the count and break if the list ever changes length.

- [ ] **Step 5: Add the CSS**

In the page's existing `<style>` block. Match the surrounding dark palette; use the page's existing CSS variables rather than new literals where they exist:

```css
.wb-board { border:1px solid var(--border); border-radius:8px; padding:14px 16px; margin:14px 0; }
.wb-board-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }
.wb-board-title { font-size:11px; letter-spacing:1.5px; color:var(--muted); }
.wb-edit-btn { background:transparent; border:1px solid var(--border2); color:var(--muted);
               border-radius:5px; padding:4px 10px; font-size:11px; cursor:pointer; }
.wb-edit-btn:hover { border-color:var(--accent); color:var(--text); }

/* Four columns: indices, sectors (itself two columns), macro. */
.wb-cols { display:grid; grid-template-columns: 1fr 2fr 1fr; gap:20px; }
.wb-group-sectors .wb-group-rows { column-count:2; column-gap:20px; }
.wb-group-label { font-size:10px; letter-spacing:1.5px; color:var(--muted); margin-bottom:8px; }
.wb-row { break-inside:avoid; margin-bottom:10px; }
.wb-name { font-size:13px; color:var(--text); }
.wb-price { font-family:var(--font-mono); font-size:15px; color:var(--text); }
.wb-move { font-family:var(--font-mono); font-size:13px; }

.wb-pos { color:#2ecc70; }
.wb-neg { color:#ff4d6d; }
.wb-flat { color:var(--muted); }

@media (max-width: 1100px) { .wb-cols { grid-template-columns: 1fr 1fr; } }
@media (max-width: 700px)  { .wb-cols { grid-template-columns: 1fr; }
                             .wb-group-sectors .wb-group-rows { column-count:1; } }
```

Check the variable names actually defined in this template before using them:
`grep -n "^\s*--" templates/weekly_review.html templates/base.html | head -20`. If `--border2`, `--accent` or `--font-mono` are not defined, substitute the nearest one that is and note the substitution in the report.

- [ ] **Step 6: Add the icons**

One inline SVG per instrument, 14px, `stroke="currentColor"`, `fill="none"`, `stroke-width="2"`. Put them in a Jinja macro keyed by instrument so the row markup stays readable:

```jinja
{% macro wb_icon(key) -%}
<svg class="wb-icon" width="14" height="14" viewBox="0 0 24 24" fill="none"
     stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
{%- if key in ('SPX','NDX','RUT') -%}<polyline points="3 17 9 11 13 15 21 7"/>
{%- elif key == 'XLK' -%}<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9z"/>
{%- elif key == 'SMH' -%}<rect x="7" y="7" width="10" height="10"/><path d="M3 10h4M3 14h4M17 10h4M17 14h4"/>
{%- elif key == 'XLF' -%}<path d="M3 21h18M5 21V9l7-5 7 5v12"/>
{%- elif key == 'XLC' -%}<path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
{%- elif key == 'XLY' -%}<path d="M6 2L3 6v14a2 2 0 002 2h14a2 2 0 002-2V6l-3-4zM3 6h18"/>
{%- elif key == 'XLI' -%}<path d="M2 20h20V10l-6 4V10l-6 4V4H2z"/>
{%- elif key == 'XLV' -%}<path d="M20.8 4.6a5.5 5.5 0 00-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 00-7.8 7.8l8.8 8.8 8.8-8.8a5.5 5.5 0 000-7.8z"/>
{%- elif key == 'XLP' -%}<path d="M5 8h14l-1 13H6zM9 8V5a3 3 0 016 0v3"/>
{%- elif key == 'XLE' -%}<polygon points="13 2 3 14 12 14 11 22 21 10 12 10"/>
{%- elif key == 'XLU' -%}<path d="M9 18h6M10 22h4M12 2a7 7 0 00-4 12.7V17h8v-2.3A7 7 0 0012 2z"/>
{%- elif key == 'XLB' -%}<path d="M12 2l9 5v10l-9 5-9-5V7z"/>
{%- elif key == 'XLRE' -%}<path d="M3 11l9-7 9 7v9a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>
{%- elif key == 'TLT' -%}<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2.5"/>
{%- elif key == 'TNX' -%}<path d="M3 3v18h18"/><polyline points="7 14 11 10 14 13 20 7"/>
{%- elif key == 'VIX' -%}<polyline points="3 12 7 12 9 5 13 19 16 12 21 12"/>
{%- elif key == 'GC' -%}<path d="M3 17h7l-1-5H4zM14 17h7l-1-5h-5zM8.5 11h7l-1-5h-5z"/>
{%- elif key == 'CL' -%}<path d="M7 4h10v16H7z"/><path d="M7 9h10M7 14h10"/>
{%- else -%}<circle cx="12" cy="12" r="9"/>
{%- endif -%}
</svg>
{%- endmacro %}
```

Use it in the row: `<div class="wb-name">{{ wb_icon(r.key) }} {{ r.label }}</div>`, and add
`.wb-icon { vertical-align:-2px; margin-right:5px; color:var(--muted); }`.

- [ ] **Step 7: Run the tests and watch them pass**

Run: `python3 -m pytest tests/test_weekly_board.py -q`
Expected: 28 passed.

- [ ] **Step 8: Mutation-check the rendering tests**

1. Change `wb_pct` so negatives render as `-0.80%` instead of `(0.80%)` → `test_negative_renders_parenthesised_and_red` must fail.
2. Swap the `wb-pos` and `wb-neg` class names in `wb_pct` → both `test_positive_renders_signed_and_green` and `test_vix_rising_renders_green_not_bearish_red` must fail.
3. Slice the row loop to `g.rows[:4]` → `test_empty_week_still_renders_every_instrument` must fail on the count of 20.

Record all three.

- [ ] **Step 9: Verify against real data**

The board must render on a real journal, not just fixtures:

```bash
SC="$(dirname "$(mktemp -u)")"; cp data/journal.db "$SC/wb.db"
python3 - <<PY
import database as db
db.DB_PATH = "$SC/wb.db"; db.init_db()
import server, app_logic as logic
server.app.config["TESTING"] = True
week = logic.current_week_monday()
with server.app.test_client() as c:
    r = c.get("/weekly-review?week=" + week)
    html = r.get_data(as_text=True)
    print("status:", r.status_code, "| rows:", html.count('class="wb-row"'))
    assert r.status_code == 200 and html.count('class="wb-row"') == 20
PY
```

Expected: `status: 200 | rows: 20`. Never point `DB_PATH` at `data/journal.db` itself.

- [ ] **Step 10: Run the whole suite and commit**

```bash
python3 -m pytest tests/ -q
git add templates/weekly_review.html tests/test_weekly_board.py
git commit -m "feat: render the weekly market board"
```

---

### Task 5: The entry table

**Files:**
- Modify: `templates/weekly_review.html` (editor markup after the board div; JS in the page's existing `<script>` block; CSS in the `<style>` block)
- Modify: `VERSION`, `CHANGELOG.md`
- Test: `tests/test_weekly_board.py` (append)

**Interfaces:**
- Consumes: `POST /api/weekly-board` from Task 3; `data.board` from Task 3.
- Produces: `wbToggleEditor()` (referenced by the button added in Task 4) and `wbSave(instrument)`.

**The tab-order requirement is load-bearing, not cosmetic.** Every cell must be a real `<input>` present in the DOM. In 4.10.0 the internals grid had to be rebuilt because its cells hid their inputs behind a click, and a `display:none` input is not focusable — Tab skipped them and the grid could not be filled from the keyboard. Do not render a value as a span that swaps to an input.

Tab must run **across** a row: Monday open, then current, then into the next instrument's open. That is the natural DOM order for one `<input>` per cell in row order — do not add `tabindex`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_weekly_board.py`:

```python
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
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m pytest tests/test_weekly_board.py -q`
Expected: FAIL with `ValueError: substring not found` — `wb-editor` does not exist.

- [ ] **Step 3: Add the editor markup**

After the `wb-board` div:

```jinja
  <div class="wb-editor" id="wb-editor" hidden data-week="{{ data.week_start }}">
    <table class="wb-table">
      <thead><tr><th>Instrument</th><th>Mon open</th><th>Current</th></tr></thead>
      <tbody>
        {% for g in data.board.groups %}{% for r in g.rows %}
        <tr>
          <td class="wb-t-name">{{ r.label }}</td>
          <td><input class="wb-input" type="text" inputmode="decimal"
                     data-instrument="{{ r.key }}" data-field="monday_open"
                     value="{{ '' if r.monday_open is none else '{:.2f}'.format(r.monday_open) }}"
                     onblur="wbSave('{{ r.key }}')"></td>
          <td><input class="wb-input" type="text" inputmode="decimal"
                     data-instrument="{{ r.key }}" data-field="current"
                     value="{{ '' if r.current is none else '{:.2f}'.format(r.current) }}"
                     onblur="wbSave('{{ r.key }}')"></td>
        </tr>
        {% endfor %}{% endfor %}
      </tbody>
    </table>
  </div>
```

`type="text"` with `inputmode="decimal"`, not `type="number"` — a number input rejects the `7,656.98` the API is built to accept, and silently clears itself on some browsers when the value does not parse.

- [ ] **Step 4: Add the JavaScript**

In the page's existing `<script>` block:

```javascript
function wbToggleEditor() {
  const el = document.getElementById('wb-editor');
  el.hidden = !el.hidden;
  if (!el.hidden) { const f = el.querySelector('.wb-input'); if (f) f.focus(); }
}

// Both cells for an instrument post together: the API writes the pair, so
// sending only the blurred field would null the other one.
async function wbSave(instrument) {
  const el = document.getElementById('wb-editor');
  const pick = f => {
    const i = el.querySelector(`[data-instrument="${instrument}"][data-field="${f}"]`);
    return i ? i.value : '';
  };
  const acct = document.getElementById('wr-root').dataset.account;
  try {
    const res = await fetch('/api/weekly-board' + (acct ? '?account=' + acct : ''), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        week_start: el.dataset.week, instrument: instrument,
        monday_open: pick('monday_open'), current: pick('current'),
      }),
    });
    const row = el.querySelector(`[data-instrument="${instrument}"]`).closest('tr');
    row.classList.toggle('wb-row-bad', !res.ok);
  } catch (e) { console.error('Board save failed', e); }
}
```

The board above the editor does not live-update — it refreshes on the next page load. Do not add a re-render; the editor is open while typing and the board is behind it.

- [ ] **Step 5: Add the editor CSS**

```css
.wb-editor { margin:0 0 14px; border:1px solid var(--border); border-radius:8px; padding:10px 14px; }
.wb-table { width:100%; border-collapse:collapse; }
.wb-table th { font-size:10px; letter-spacing:1px; color:var(--muted);
               text-align:left; font-weight:500; padding:4px 8px; }
.wb-table td { padding:2px 8px; }
.wb-t-name { font-size:12px; color:var(--text); width:140px; }
.wb-input { background:transparent; border:1px solid transparent; border-radius:4px;
            color:var(--text); font-family:var(--font-mono); font-size:13px;
            padding:4px 8px; width:110px; outline:none; }
.wb-input:hover { border-color:var(--border2); }
.wb-input:focus { border-color:var(--accent); }
.wb-row-bad .wb-input { border-color:#ff4d6d; }
```

- [ ] **Step 6: Run the tests and watch them pass**

Run: `python3 -m pytest tests/test_weekly_board.py -q`
Expected: 31 passed.

- [ ] **Step 7: Mutation-check the tab-order tests**

1. Swap the two `<td>` blocks so current precedes open → `test_editor_inputs_are_ordered_open_then_current_per_row` must fail.
2. Wrap the `current` input in `<span style="display:none">` → `test_editor_cells_are_never_hidden` must fail.
3. Render only the first group's rows → `test_editor_renders_two_real_inputs_per_instrument` must fail on the count of 40.

Record all three.

- [ ] **Step 8: Check the JavaScript parses**

```bash
python3 - <<'PY'
import re, subprocess, tempfile, os
s = open("templates/weekly_review.html").read()
js = "\n".join(m for m in re.findall(r"<script[^>]*>(.*?)</script>", s, re.S) if "src=" not in m)
js = re.sub(r"\{\{.*?\}\}", "0", js); js = re.sub(r"\{%.*?%\}", "", js)
t = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False); t.write(js); t.close()
r = subprocess.run(["node", "--check", t.name], capture_output=True, text=True)
print("JS parse:", "OK" if r.returncode == 0 else "FAIL\n" + r.stderr[:600]); os.unlink(t.name)
PY
```

Expected: `JS parse: OK`.

- [ ] **Step 9: Verify the round trip against real data**

```bash
SC="$(dirname "$(mktemp -u)")"; cp data/journal.db "$SC/wb2.db"
python3 - <<PY
import database as db
db.DB_PATH = "$SC/wb2.db"; db.init_db()
import server, app_logic as logic
server.app.config["TESTING"] = True
week = logic.current_week_monday()
with server.app.test_client() as c:
    assert c.post("/api/weekly-board", json={
        "week_start": week, "instrument": "SPX",
        "monday_open": "7,600.00", "current": "7,656.98"}).status_code == 200
    html = c.get("/weekly-review?week=" + week).get_data(as_text=True)
    print("price rendered:", "7,656.98" in html)
    print("pct rendered:", 'wb-pos">+0.75%' in html)
    assert "7,656.98" in html
PY
```

Expected: both `True`.

- [ ] **Step 10: Bump the version and update the changelog**

```bash
echo "4.11.0" > VERSION
```

Add to `CHANGELOG.md` above the `## [4.10.0]` entry, matching the file's existing voice:

```markdown
## [4.11.0] — 2026-09-14

### Added

- **A market board on the weekly review page.** Twenty instruments — three cash indices, twelve
  sectors including SMH, five macro — each showing its percent move from Monday's open, in the
  screenshot's four-column shape and the app's dark palette. Values are entered in an inline table
  that autosaves on blur; Monday's open is typed once a week and the current price is retyped on a
  refresh.
- Percent is computed on read and never stored. Prices accept the thousands separators that
  actually get typed, and `nan`/`inf` are rejected at the boundary rather than poisoning a percent
  downstream.

### Note

- The board colours **green for up and red for down on every instrument**, including VIX, the 10-year
  yield and oil — deliberately unlike the internals delta pills, where a rise in those three is
  bearish and shows dark red. Internals is a signal surface; the board is a market surface. See
  `docs/superpowers/specs/2026-09-14-weekly-market-board-design.md`.
```

- [ ] **Step 11: Run the whole suite and commit**

```bash
python3 -m pytest tests/ -q
git add templates/weekly_review.html VERSION CHANGELOG.md tests/test_weekly_board.py
git commit -m "feat: weekly board entry table"
```

**Do not push.**

---

## Human verification

No JavaScript test infrastructure exists in this repo, so these need eyes on screen:

1. Open `Edit values`, type in the first Monday-open cell, and press Tab repeatedly. The cursor must go open → current → next instrument's open, never sideways into another column.
2. Enter a Monday open and a lower current for a sector; confirm the board shows a parenthesised red percent after reload.
3. Enter a rising VIX; confirm it is **green** on the board while the internals delta pill for a rising VIX is still **red**. Both are correct.
4. Check the four-column layout at full width, and that it collapses sanely at tablet and phone widths.
5. Confirm the 20 icons render and are legible at 14px on the dark ground.
