# Planned Exit Capture & Plan-vs-Execution Review — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture a planned exit per entry decision and a hand-recorded peak price per trade, then surface a weekly Plan-vs-Execution review that shows whether exits are driven by fear, greed, or a market that never paid.

**Architecture:** Two independent capture paths feeding one read-only report. The **target** path mirrors the existing per-tranche `stop_price` plumbing exactly (live form → `live_trade_executions` → carried to `fills` on push). The **peak** path is journal-side only (a backfill strip on the day page → `trades`). All analysis is derived on read in `app_logic.py`; nothing computed is ever stored.

**Tech Stack:** Python 3, Flask, SQLite (stdlib `sqlite3`), server-rendered Jinja templates with vanilla JS. Tests via pytest (introduced by Task 1 — the project currently has none).

**Spec:** `docs/superpowers/specs/2026-09-06-planned-exit-capture-design.md`

## Global Constraints

- **Three-layer rule.** SQL lives only in `database.py`. Math and business logic live only in `app_logic.py`. `server.py` holds routes only — no SQL, no math.
- **Nothing derived is persisted.** No stored R:R, capture %, risk, verdict, or excursion. All derived on read, every time.
- **Additive migrations only.** Guarded `ALTER TABLE ... ADD COLUMN` inside `init_db()` (`database.py:143`), following the existing pattern at `database.py:300-315`. `init_db()` must stay safe to run repeatedly — it runs on every request via `@app.before_request` (`server.py:22`).
- **Update `SCHEMA.md`** in the same commit as any schema change (project rule).
- **Bump `CHANGELOG.md` and `VERSION`** to `4.8.0` (project rule). Current version is `4.7.0`.
- **Commit straight to `main` and push.** Never branch, never open a PR (project rule).
- **Backward-compatible signatures.** Every changed function signature adds keyword arguments with defaults so existing callers keep working untouched.

### Exact values, copied from the spec

| Constant | Value | Where it lives |
|---|---|---|
| `target_source` values | `'none'` \| `'entered'` \| `'edited'` | §1 |
| Default `target_source` | `'none'` | §1 |
| Tolerance band | `0.10` | `app_config` key `plan_capture_band`, §5 |
| Capture epsilon | `0.25` (one tick) | `PLAN_EPSILON` in `app_logic.py`, §5 |
| Peak window default | `30` minutes | `app_config` key `mfe_window_minutes`, §6.2 |
| `mfe_timing` values | `'during'` \| `'after'` | §6.1 |

### Real data conventions (verified against `data/journal.db` — do not guess these)

- `trades.direction` is `'Long'` or `'Short'` (capitalised, not `'LONG'`).
- `fills.side` is `'Buy'` or `'Sell'`. An **entry fill** is `Buy` on a `Long` trade, `Sell` on a `Short` trade.
- `live_trade_executions.exec_type` is **mixed case**: `'OPEN'`, `'ADD'`, `'EXIT'`, `'STOP'`, but also `'tp_hit'`, `'stop_hit'`, `'manual_exit'`.
  **Therefore: never enumerate exit types.** An exit-side row is any row where `UPPER(exec_type) NOT IN ('OPEN','ADD')`. This matches the `isEntry` test in `buildTransactionFeed` (`templates/live_v2.html:7171`) and is immune to new lowercase exit types.
- `INSTRUMENT_CONFIG` (`app_logic.py:618`): MES = 5 $/point, ES = 50 $/point. Read it through `get_instrument_config()` (`app_logic.py:660`), which applies DB overrides.
- Instrument for a journal trade is in `trades.execution_json`, key `instrument`.

---

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `tests/conftest.py` | pytest fixtures: throwaway SQLite DB, Flask test client |
| `tests/test_target_capture.py` | Target schema, DB layer, routes, freeze, journal carry-through |
| `tests/test_peak_capture.py` | Peak schema, DB layer, route validation |
| `tests/test_plan_analysis.py` | All derivation math: weighting, capture %, buckets, verdicts, excursion, realism, coverage |
| `pytest.ini` | Test discovery config |

**Modified:**

| File | Change |
|---|---|
| `database.py` | Migrations; target/peak read+write functions; one batched entry-fill query |
| `app_logic.py` | Exit tag vocabulary; all plan-vs-execution derivation; weekly payload extension |
| `server.py` | Target params on 2 existing routes; 2 new routes |
| `templates/live_v2.html` | Target input on Entry + Add forms; Target column in Manage ledger |
| `templates/day.html` | `PLAN CHECK` backfill strip |
| `templates/weekly_review.html` | `PLAN vs EXECUTION` section |
| `SCHEMA.md`, `CHANGELOG.md`, `VERSION` | Documentation and version (project rules) |

**A note on testing the UI.** This project has no JavaScript test infrastructure and this plan does not add any — that would be a much larger change than the feature warrants. The mitigation is architectural: **every non-trivial computation lives in Python and is unit-tested** (Task 10), leaving the templates as thin rendering. The four UI tasks (5, 6, 8, 11) therefore carry **explicit manual verification steps** instead of automated tests. Follow them literally; they are the only safety net those tasks have.

---

## Task 1: Test harness

The project has zero tests and pytest is not installed. Every later task depends on this. The deliverable is a harness proven to work by one real test against a throwaway database.

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_target_capture.py`
- Create: `pytest.ini`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: nothing.
- Produces: pytest fixtures `tmp_db` (patches `database.DB_PATH` to a temp file and builds the schema; returns the path as `str`) and `client` (Flask test client bound to that same temp DB). Every later test task uses these two names.

- [ ] **Step 1: Add pytest to requirements**

Append to `requirements.txt`:

```
pytest>=8.0.0
```

- [ ] **Step 2: Install it**

Run: `python3 -m pip install -r requirements.txt`
Expected: pytest installs successfully.

- [ ] **Step 3: Write the pytest config**

Create `pytest.ini`:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_functions = test_*
addopts = -q
```

- [ ] **Step 4: Write the fixtures**

Create `tests/conftest.py`:

```python
"""Shared fixtures. Every test runs against a throwaway SQLite file, never data/journal.db."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db  # noqa: E402


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """Point the whole app at a throwaway DB and build the schema.

    get_conn() reads the module-level DB_PATH at call time, so patching the
    attribute redirects database.py, app_logic.py and server.py at once.
    """
    path = tmp_path / "data" / "journal.db"
    monkeypatch.setattr(db, "DB_PATH", str(path))
    db.init_db()
    return str(path)


@pytest.fixture
def client(tmp_db):
    """Flask test client bound to the same throwaway DB."""
    import server

    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


@pytest.fixture
def day_id(tmp_db):
    """A trading day to hang journal trades off. upsert_day returns an int id."""
    return db.upsert_day("2026-09-01", None)
```

- [ ] **Step 5: Write a smoke test that proves the harness isolates the DB**

Create `tests/test_target_capture.py`:

```python
import database as db


def test_harness_uses_a_throwaway_db(tmp_db):
    """The schema is built in the temp file, and it is not the repo's journal."""
    import os
    repo_db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "journal.db")
    assert os.path.abspath(tmp_db) != os.path.abspath(repo_db)
    assert os.path.exists(tmp_db)
    with db.get_conn() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    assert "trades" in tables
    assert "fills" in tables
    assert "live_trade_executions" in tables


def test_init_db_is_rerunnable(tmp_db):
    """init_db runs on every request; running it twice must not raise."""
    db.init_db()
    db.init_db()
    with db.get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(fills)").fetchall()]
    assert cols.count("stop_price") == 1
```

- [ ] **Step 6: Run the tests**

Run: `python3 -m pytest tests/test_target_capture.py -v`
Expected: 2 passed.

- [ ] **Step 7: Verify the real database was untouched**

Run: `git status --short data/`
Expected: no output. If `data/journal.db` shows as modified, the fixture is not isolating —
stop and fix before continuing, or later tasks will corrupt real trading data.

- [ ] **Step 8: Commit**

```bash
git add tests/ pytest.ini requirements.txt
git commit -m "test: add pytest harness with isolated temp database

Project had no test infrastructure. Adds a tmp_db fixture that patches
database.DB_PATH so tests never touch data/journal.db, plus a Flask
client fixture bound to the same temp DB."
```

---

## Task 2: Target — schema and database layer

**Files:**
- Modify: `database.py` (migration block after `database.py:315`; `insert_fill` at `database.py:1130`; `add_live_trade_execution` at `database.py:1964`; new functions after `database.py:1981`)
- Modify: `SCHEMA.md`
- Test: `tests/test_target_capture.py`

**Interfaces:**
- Consumes: `tmp_db` fixture from Task 1.
- Produces:
  - `insert_fill(trade_id, fill_time, side, qty, price, exit_type=None, stop_price=None, stop_source='default', target_price=None, target_source='none')`
  - `add_live_trade_execution(live_trade_id, exec_type, portion, qty, price, exec_time, pnl, stop_price=None, stop_source='default', target_price=None, target_source='none')`
  - `update_live_trade_execution_target(exec_id, target_price, target_source='edited') -> None`
  - `live_trade_has_exit(live_trade_id) -> bool`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_target_capture.py`:

```python
def test_target_columns_exist_on_both_ledgers(tmp_db):
    with db.get_conn() as conn:
        fill_cols = [r[1] for r in conn.execute("PRAGMA table_info(fills)").fetchall()]
        lte_cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(live_trade_executions)").fetchall()]
    for cols in (fill_cols, lte_cols):
        assert "target_price" in cols
        assert "target_source" in cols


def test_target_migration_is_rerunnable(tmp_db):
    db.init_db()
    db.init_db()
    with db.get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(fills)").fetchall()]
    assert cols.count("target_price") == 1
    assert cols.count("target_source") == 1


def test_target_defaults_to_none_source_and_null_price(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7715.0, 7731.0, 240.0,
                               "17:32", "18:02")
    db.insert_fill(trade_id, "17:32", "Buy", 3, 7715.0)
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT target_price, target_source FROM fills WHERE trade_id = ?",
            (trade_id,)).fetchone()
    assert row["target_price"] is None
    assert row["target_source"] == "none"


def test_insert_fill_stores_an_entered_target(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7715.0, 7731.0, 240.0,
                               "17:32", "18:02")
    db.insert_fill(trade_id, "17:32", "Buy", 3, 7715.0,
                   stop_price=7688.5, stop_source="entered",
                   target_price=7760.0, target_source="entered")
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT target_price, target_source FROM fills WHERE trade_id = ?",
            (trade_id,)).fetchone()
    assert row["target_price"] == 7760.0
    assert row["target_source"] == "entered"


def test_update_live_trade_execution_target_sets_edited(tmp_db):
    live_id = db.create_live_trade(None, "Long", "MES", 7715.0, "17:32", 3, "full")
    exec_id = db.add_live_trade_execution(live_id, "OPEN", 1, 3, 7715.0, "17:32", 0.0)
    db.update_live_trade_execution_target(exec_id, 7770.0)
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT target_price, target_source FROM live_trade_executions WHERE id = ?",
            (exec_id,)).fetchone()
    assert row["target_price"] == 7770.0
    assert row["target_source"] == "edited"


def test_live_trade_has_exit_ignores_case_of_exec_type(tmp_db):
    """exec_type is mixed case in real data: OPEN/ADD/EXIT but also tp_hit,
    stop_hit, manual_exit. Anything that is not OPEN/ADD is an exit."""
    live_id = db.create_live_trade(None, "Long", "MES", 7715.0, "17:32", 3, "full")
    db.add_live_trade_execution(live_id, "OPEN", 1, 3, 7715.0, "17:32", 0.0)
    assert db.live_trade_has_exit(live_id) is False

    db.add_live_trade_execution(live_id, "ADD", 1, 2, 7720.0, "17:40", 0.0)
    assert db.live_trade_has_exit(live_id) is False

    db.add_live_trade_execution(live_id, "manual_exit", 1, 5, 7731.0, "18:02", 240.0)
    assert db.live_trade_has_exit(live_id) is True
```

These signatures were verified against the real code:
`insert_trade(day_id, trade_num, direction, qty, avg_entry, avg_exit, pnl, entry_time, exit_time, ...)`
(`database.py:1120`) and
`create_live_trade(account_id, direction, instrument, entry_price, entry_time, total_qty, mode, ...)`
(`database.py:1858`). If `create_live_trade` returns something other than the new id, unwrap it —
do not change the production signature to fit the test.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_target_capture.py -v`
Expected: FAIL — `assert 'target_price' in cols` fails, and
`AttributeError: module 'database' has no attribute 'update_live_trade_execution_target'`.

- [ ] **Step 3: Add the migration**

In `database.py`, immediately after the `live_trade_executions` stop-column block that ends at
`database.py:315`, insert:

```python
        # Migration: planned exit (target) capture per entry decision. Mirrors
        # stop_price/stop_source. target_source: 'none' (no plan recorded),
        # 'entered' (typed on the Entry/Add form), 'edited' (ledger edit before
        # any exit). There is no default target — NULL means no plan existed,
        # which is a finding in its own right. Derived on read, never persisted.
        fill_cols = [r[1] for r in conn.execute("PRAGMA table_info(fills)").fetchall()]
        if "target_price" not in fill_cols:
            conn.execute("ALTER TABLE fills ADD COLUMN target_price REAL")
        if "target_source" not in fill_cols:
            conn.execute("ALTER TABLE fills ADD COLUMN target_source TEXT NOT NULL DEFAULT 'none'")
        lte_cols = [r[1] for r in conn.execute("PRAGMA table_info(live_trade_executions)").fetchall()]
        if "target_price" not in lte_cols:
            conn.execute("ALTER TABLE live_trade_executions ADD COLUMN target_price REAL")
        if "target_source" not in lte_cols:
            conn.execute("ALTER TABLE live_trade_executions ADD COLUMN target_source TEXT NOT NULL DEFAULT 'none'")
```

- [ ] **Step 4: Extend `insert_fill`**

Replace `insert_fill` at `database.py:1130`:

```python
def insert_fill(trade_id, fill_time, side, qty, price, exit_type=None,
                stop_price=None, stop_source='default',
                target_price=None, target_source='none'):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO fills (trade_id, fill_time, side, qty, price, exit_type, "
            "stop_price, stop_source, target_price, target_source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trade_id, fill_time, side, qty, price, exit_type,
             stop_price, stop_source, target_price, target_source)
        )
```

- [ ] **Step 5: Extend `add_live_trade_execution`**

Replace `add_live_trade_execution` at `database.py:1964`:

```python
def add_live_trade_execution(live_trade_id, exec_type, portion, qty, price, exec_time, pnl,
                             stop_price=None, stop_source='default',
                             target_price=None, target_source='none'):
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO live_trade_executions
                (live_trade_id, exec_type, portion, qty, price, exec_time, pnl,
                 stop_price, stop_source, target_price, target_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (live_trade_id, exec_type, portion, qty, price, exec_time, pnl,
              stop_price, stop_source, target_price, target_source))
        return cur.lastrowid
```

Keep whatever the existing function returns. If it currently returns nothing, check its callers
with `grep -n "add_live_trade_execution(" server.py app_logic.py` before changing the return.

- [ ] **Step 6: Add the two new functions**

After `update_live_trade_execution_stop` (ends `database.py:1981`):

```python
def update_live_trade_execution_target(exec_id, target_price, target_source='edited'):
    """Set the planned exit on one OPEN/ADD row. Freeze enforcement lives in the
    route (server.py), which checks live_trade_has_exit first."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE live_trade_executions SET target_price = ?, target_source = ? WHERE id = ?",
            (target_price, target_source, exec_id)
        )


def live_trade_has_exit(live_trade_id):
    """True once any exit-side execution exists on this trade.

    exec_type is mixed case in real data ('EXIT' but also 'tp_hit', 'stop_hit',
    'manual_exit'), so this tests the complement of the entry types rather than
    enumerating exit types — the same rule buildTransactionFeed uses client-side.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM live_trade_executions "
            "WHERE live_trade_id = ? AND UPPER(exec_type) NOT IN ('OPEN', 'ADD') LIMIT 1",
            (live_trade_id,)
        ).fetchone()
    return row is not None
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_target_capture.py -v`
Expected: all pass.

- [ ] **Step 8: Update `SCHEMA.md`**

In section `### 4. FILLS`, add below the `stop_source` row:

```
| target_price  | REAL  | Nullable. Planned exit captured at this entry decision (per-tranche). NULL on exit-side fills and when no plan was recorded. |
| target_source | TEXT  | NOT NULL DEFAULT 'none'. One of 'none' (no plan recorded), 'entered' (typed on form), 'edited' (ledger edit before any exit). |
```

In section `### 11. LIVE_TRADE_EXECUTIONS`, add the same two rows below its `stop_source` row,
then extend the note beneath it:

```
> Mirrors `fills.target_price`/`target_source`. Unlike the stop there is no default target:
> NULL means no plan existed. Frozen once any exit-side execution exists on the trade.
```

- [ ] **Step 9: Commit**

```bash
git add database.py SCHEMA.md tests/test_target_capture.py
git commit -m "feat: add planned exit (target) columns to fills and live_trade_executions

Mirrors the per-tranche stop_price/stop_source plumbing. No default target:
NULL means no plan was recorded, which the weekly review counts as its own
discipline stat. Adds live_trade_has_exit for the freeze rule, which tests
the complement of OPEN/ADD because exec_type is mixed case in real data."
```

---

## Task 3: Target — routes

**Files:**
- Modify: `server.py` (`POST /api/live` near `server.py:1015`; `POST /api/live/<id>/add` near `server.py:1218`; new route after `server.py:1502`)
- Test: `tests/test_target_capture.py`

**Interfaces:**
- Consumes: `db.update_live_trade_execution_target`, `db.live_trade_has_exit`, `db.add_live_trade_execution` (Task 2).
- Produces: `PATCH /api/live/<live_id>/execution/<exec_id>/target` accepting `{"target_price": float}`, returning `{"ok": True}` on success, `400` on a missing or unparseable price, `409` once the trade has any exit.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_target_capture.py`:

```python
def test_create_live_trade_stores_entered_target(client, tmp_db):
    res = client.post("/api/live", json={
        "direction": "Long", "instrument": "MES", "entry_price": 7715.0,
        "total_qty": 3, "entry_time": "17:32",
        "stop_price": 7688.5, "target_price": 7760.0,
    })
    assert res.status_code == 200
    live_id = res.get_json()["id"]
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT target_price, target_source FROM live_trade_executions "
            "WHERE live_trade_id = ? AND exec_type = 'OPEN'", (live_id,)).fetchone()
    assert row["target_price"] == 7760.0
    assert row["target_source"] == "entered"


def test_create_live_trade_without_target_stores_none(client, tmp_db):
    res = client.post("/api/live", json={
        "direction": "Long", "instrument": "MES", "entry_price": 7715.0,
        "total_qty": 3, "entry_time": "17:32",
    })
    live_id = res.get_json()["id"]
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT target_price, target_source FROM live_trade_executions "
            "WHERE live_trade_id = ? AND exec_type = 'OPEN'", (live_id,)).fetchone()
    assert row["target_price"] is None
    assert row["target_source"] == "none"


def test_patch_target_before_any_exit_succeeds(client, tmp_db):
    live_id = client.post("/api/live", json={
        "direction": "Long", "instrument": "MES", "entry_price": 7715.0,
        "total_qty": 3, "entry_time": "17:32",
    }).get_json()["id"]
    with db.get_conn() as conn:
        exec_id = conn.execute(
            "SELECT id FROM live_trade_executions WHERE live_trade_id = ?",
            (live_id,)).fetchone()["id"]

    res = client.patch(f"/api/live/{live_id}/execution/{exec_id}/target",
                       json={"target_price": 7770.0})
    assert res.status_code == 200
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT target_price, target_source FROM live_trade_executions WHERE id = ?",
            (exec_id,)).fetchone()
    assert row["target_price"] == 7770.0
    assert row["target_source"] == "edited"


def test_patch_target_after_an_exit_returns_409_and_changes_nothing(client, tmp_db):
    """The freeze. Enforced server-side so a stale tab cannot slip past the UI lock."""
    live_id = client.post("/api/live", json={
        "direction": "Long", "instrument": "MES", "entry_price": 7715.0,
        "total_qty": 3, "entry_time": "17:32", "target_price": 7760.0,
    }).get_json()["id"]
    with db.get_conn() as conn:
        exec_id = conn.execute(
            "SELECT id FROM live_trade_executions WHERE live_trade_id = ?",
            (live_id,)).fetchone()["id"]

    db.add_live_trade_execution(live_id, "manual_exit", 1, 3, 7731.0, "18:02", 240.0)

    res = client.patch(f"/api/live/{live_id}/execution/{exec_id}/target",
                       json={"target_price": 7999.0})
    assert res.status_code == 409
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT target_price FROM live_trade_executions WHERE id = ?",
            (exec_id,)).fetchone()
    assert row["target_price"] == 7760.0


def test_patch_target_rejects_missing_price(client, tmp_db):
    live_id = client.post("/api/live", json={
        "direction": "Long", "instrument": "MES", "entry_price": 7715.0,
        "total_qty": 3, "entry_time": "17:32",
    }).get_json()["id"]
    with db.get_conn() as conn:
        exec_id = conn.execute(
            "SELECT id FROM live_trade_executions WHERE live_trade_id = ?",
            (live_id,)).fetchone()["id"]
    res = client.patch(f"/api/live/{live_id}/execution/{exec_id}/target", json={})
    assert res.status_code == 400
```

The `POST /api/live` body keys must match what the real route reads. Confirm with
`sed -n '995,1045p' server.py` and adjust the test payloads — not the route — if they differ.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_target_capture.py -v`
Expected: FAIL — target columns stay NULL/`'none'` on create, and the PATCH route 404s.

- [ ] **Step 3: Read the target on trade creation**

In `server.py`, in the `POST /api/live` handler beside the existing `stop_price` block at
`server.py:1015-1020`, add:

```python
    # Planned exit. No default: absent means no plan was recorded.
    if body.get("target_price") not in (None, ""):
        open_target_price = float(body["target_price"])
        open_target_source = "entered"
    else:
        open_target_price = None
        open_target_source = "none"
```

Then extend the `db.add_live_trade_execution(...)` call for the OPEN row (`server.py:1039`) with:

```python
        target_price=open_target_price, target_source=open_target_source
```

- [ ] **Step 4: Read the target on add**

In the `POST /api/live/<id>/add` handler beside the `stop_price` block at `server.py:1218-1222`:

```python
    if body.get("target_price") not in (None, ""):
        add_target_price = float(body["target_price"])
        add_target_source = "entered"
    else:
        add_target_price = None
        add_target_source = "none"
```

Then extend the `db.add_live_trade_execution(...)` call at `server.py:1227` with:

```python
        target_price=add_target_price, target_source=add_target_source
```

- [ ] **Step 5: Add the PATCH route**

In `server.py`, directly after the existing `.../stop` route (which ends at `server.py:1502`):

```python
@app.route("/api/live/<int:live_id>/execution/<int:exec_id>/target", methods=["PATCH"])
def api_update_execution_target(live_id, exec_id):
    """Edit the planned exit on one OPEN/ADD row.

    Frozen at the first exit: a target is a record of intent, so allowing edits
    after the outcome is known would let the weekly review confirm itself.
    Enforced here rather than only in the UI so a stale tab cannot bypass it.
    """
    if db.live_trade_has_exit(live_id):
        return jsonify({"error": "Planned exit is locked once the trade has an exit"}), 409
    body = request.get_json(silent=True) or {}
    if body.get("target_price") in (None, ""):
        return jsonify({"error": "target_price is required"}), 400
    try:
        target_price = float(body["target_price"])
    except (TypeError, ValueError):
        return jsonify({"error": "target_price must be a number"}), 400
    db.update_live_trade_execution_target(exec_id, target_price, "edited")
    return jsonify({"ok": True})
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_target_capture.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add server.py tests/test_target_capture.py
git commit -m "feat: accept planned exit on entry/add, add PATCH target route

The PATCH route returns 409 once the trade has any exit-side execution.
Enforced server-side rather than only hidden in the UI, because a UI-only
lock is decorative and the freeze is what makes the weekly fear/greed
read trustworthy."
```

---

## Task 4: Target — carry-through to journal

**Files:**
- Modify: `app_logic.py` (`close_live_trade_to_journal`, the three `insert_fill` calls at `app_logic.py:1208`, `1221`, `1225`)
- Test: `tests/test_target_capture.py`

**Interfaces:**
- Consumes: `db.insert_fill` with target kwargs (Task 2).
- Produces: journal `fills` rows carrying `target_price`/`target_source` on entry-side rows only. Task 10 reads these.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_target_capture.py`:

```python
import app_logic as logic


def test_push_to_journal_carries_target_onto_entry_fills_only(client, tmp_db):
    live_id = client.post("/api/live", json={
        "direction": "Long", "instrument": "MES", "entry_price": 7715.0,
        "total_qty": 3, "entry_time": "17:32",
        "stop_price": 7688.5, "target_price": 7760.0,
    }).get_json()["id"]
    db.add_live_trade_execution(live_id, "manual_exit", 1, 3, 7731.0, "18:02", 240.0)

    trade_id = logic.close_live_trade_to_journal(live_id)

    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT side, target_price, target_source FROM fills WHERE trade_id = ? "
            "ORDER BY side", (trade_id,)).fetchall()

    entry = [r for r in rows if r["side"] == "Buy"]
    exits = [r for r in rows if r["side"] == "Sell"]
    assert entry and exits
    assert entry[0]["target_price"] == 7760.0
    assert entry[0]["target_source"] == "entered"
    for r in exits:
        assert r["target_price"] is None
        assert r["target_source"] == "none"
```

`close_live_trade_to_journal` may return something other than a bare trade id. Check with
`sed -n '1095,1105p' app_logic.py` and unwrap the id accordingly.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_target_capture.py::test_push_to_journal_carries_target_onto_entry_fills_only -v`
Expected: FAIL — `assert None == 7760.0`, because the target is not passed through.

- [ ] **Step 3: Carry the target on entry-side execs**

In `app_logic.py`, extend the `insert_fill` call at `app_logic.py:1208`:

```python
            db.insert_fill(trade_id, e["exec_time"], entry_side, e["qty"], e["price"],
                           exit_type=None,
                           stop_price=e.get("stop_price"),
                           stop_source=e.get("stop_source") or "default",
                           target_price=e.get("target_price"),
                           target_source=e.get("target_source") or "none")
```

- [ ] **Step 4: Handle the legacy synthesized entry fill**

At `app_logic.py:1221` (the path with no OPEN execution row), add explicit target arguments so
the intent is on the page rather than relying on the default:

```python
        db.insert_fill(trade_id, lt["entry_time"], entry_side, lt["total_qty"], lt["entry_price"],
                       exit_type=None, stop_price=legacy_stop, stop_source=legacy_source,
                       target_price=None, target_source="none")
```

- [ ] **Step 5: Keep exit fills explicitly target-free**

At `app_logic.py:1225`:

```python
        db.insert_fill(trade_id, e["exec_time"], exit_side, e["qty"], e["price"],
                       exit_type=e.get("exec_type"), stop_price=None, stop_source='default',
                       target_price=None, target_source='none')
```

- [ ] **Step 6: Run the whole suite**

Run: `python3 -m pytest tests/ -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app_logic.py tests/test_target_capture.py
git commit -m "feat: carry planned exit onto entry fills when pushing to journal"
```

---

## Task 5: Target — Entry and Add form inputs

No automated tests (no JS test infrastructure). Follow the manual verification steps literally.

**Files:**
- Modify: `templates/live_v2.html` (entry form markup at `live_v2.html:4982-4989`; `efUpdateRisk` at `live_v2.html:5028`; keydown list at `live_v2.html:5018`; `handleEnterClick` at `live_v2.html:8151`; `window._pendingEntry` consumer at `live_v2.html:8218`; `buildAddContractsForm` at `live_v2.html:7324`; `dynSubmitAdd` at `live_v2.html:7407`)

**Interfaces:**
- Consumes: `POST /api/live` and `POST /api/live/<id>/add` accepting optional `target_price` (Task 3).
- Produces: nothing other tasks consume.

- [ ] **Step 1: Add the Target row to the entry form**

In `templates/live_v2.html`, between the Stop row (ends `live_v2.html:4985`) and the Risk row,
insert:

```html
      <div class="ef-row">
        <span class="ef-label">Target</span>
        <input type="number" step="0.25" class="ef-input" id="ef-target" placeholder="optional" autocomplete="off" oninput="efUpdateRisk()">
      </div>
```

The placeholder reads `optional`, not a default value — unlike the stop there is no auto target,
and a blank target is a legitimate recorded state (`'none'`).

- [ ] **Step 2: Show R:R in the risk readout**

Replace the last two lines of `efUpdateRisk` (`live_v2.html:5041-5043`):

```js
  const risk = Math.abs(price - stop) * qty * pv;
  const targetInp = document.getElementById('ef-target');
  const target = targetInp && targetInp.value !== '' ? parseFloat(targetInp.value) : null;
  let rr = '';
  if (target != null && !isNaN(target)) {
    const riskPts = Math.abs(price - stop);
    const rewardPts = formDir === 'Long' ? (target - price) : (price - target);
    if (riskPts > 0 && rewardPts > 0) rr = ' · ' + (rewardPts / riskPts).toFixed(1) + 'R';
  }
  el.textContent = _fmtRisk(risk) + (typed ? '' : ' · 20pt default') + rr;
  el.classList.toggle('default-risk', !typed);
```

R:R is omitted when the target is blank, unparseable, or on the wrong side of entry — a target
below entry on a long is a typo, and showing a negative R would dress it up as information.

- [ ] **Step 3: Submit on Enter from the target field too**

At `live_v2.html:5018`, extend the id list:

```js
  ['ef-price','ef-qty','ef-stop','ef-target'].forEach(id => {
```

- [ ] **Step 4: Read the target in `handleEnterClick`**

After the `stop_price` lines at `live_v2.html:8159-8160`:

```js
  // Optional planned exit; omit entirely so the server records 'none'.
  const targetRaw = document.getElementById('ef-target')?.value;
  const target_price = (targetRaw !== undefined && targetRaw !== '') ? parseFloat(targetRaw) : null;
```

Then change the `_pendingEntry` assignment at `live_v2.html:8163`:

```js
  window._pendingEntry = { price, qty, time, stop_price, target_price };
```

- [ ] **Step 5: Send the target on create**

At `live_v2.html:8218`, destructure the new field:

```js
  const { price, qty, time, stop_price, target_price } = window._pendingEntry || {};
```

Then in the request body beside `stop_price` (`live_v2.html:8233`):

```js
      target_price: (target_price != null ? target_price : undefined),
```

- [ ] **Step 6: Add the Target field to the Add form**

In `buildAddContractsForm` (`live_v2.html:7324`), between the Stop and Risk lines:

```html
    <label>Target</label><input type="number" step="0.25" id="dyn-add-target" placeholder="optional" oninput="dynAddUpdateRisk()">
```

- [ ] **Step 7: Send the target on add**

In `dynSubmitAdd` (`live_v2.html:7407`), after the `stop_price` lines:

```js
  const targetRaw = document.getElementById('dyn-add-target')?.value;
  const target_price = (targetRaw !== undefined && targetRaw !== '') ? parseFloat(targetRaw) : null;
```

Then replace the body construction (`live_v2.html:7420`) — the conditional spread keeps blank
fields out of the payload entirely, so the server sees an absent key rather than a null:

```js
      body: JSON.stringify(Object.assign({ price, qty, time },
        stop_price != null ? { stop_price } : {},
        target_price != null ? { target_price } : {}))
```

- [ ] **Step 8: Manual verification — start the app**

Run: `python3 server.py`
Open `http://127.0.0.1:5050`, go to the Trade V2 page, ENTRY tab.

- [ ] **Step 9: Manual verification — R:R appears and disappears**

1. Direction LONG, instrument MES, Price `7715`, Qty `3`, Stop `7688.50`.
   Expect Risk to read `$398 · ` with no R suffix.
2. Type Target `7760`.
   Expect Risk to read `$398 · 1.7R`.
3. Change Target to `7700` (below entry on a long — a typo).
   Expect the R suffix to disappear rather than show a negative.
4. Clear Target.
   Expect the R suffix to stay gone and the readout to be unchanged from step 1.

- [ ] **Step 10: Manual verification — the target is stored**

Press ENTER to open the trade. Then run:

```bash
python3 -c "
import database as db
with db.get_conn() as c:
    for r in c.execute('SELECT exec_type, price, stop_price, target_price, target_source FROM live_trade_executions ORDER BY id DESC LIMIT 3'):
        print(dict(r))
"
```

Expected: the OPEN row shows `target_price: 7760.0` and `target_source: 'entered'`.

- [ ] **Step 11: Manual verification — a blank target records 'none'**

Open a second trade leaving Target blank. Re-run the query above.
Expected: the new OPEN row shows `target_price: None` and `target_source: 'none'`.

- [ ] **Step 12: Commit**

```bash
git add templates/live_v2.html
git commit -m "feat: planned exit input on entry and add forms with live R:R

Blank is a legitimate state and posts no key at all, so the server records
'none' rather than a fabricated default. R:R is suppressed when the target
sits on the wrong side of entry rather than showing a negative."
```

---

## Task 6: Target — Manage ledger column and freeze

**Files:**
- Modify: `templates/live_v2.html` (`buildTransactionFeed` at `live_v2.html:7163`; column header at `live_v2.html:7237`; footer at `live_v2.html:7215-7231`; new edit function beside `dynEditTrancheStop` at `live_v2.html:7243`)

**Interfaces:**
- Consumes: `PATCH /api/live/<id>/execution/<exec_id>/target` (Task 3).
- Produces: nothing other tasks consume.

- [ ] **Step 1: Add a helper that detects an exit on the client**

Above `buildTransactionFeed` in `live_v2.html`, add:

```js
// Mirrors db.live_trade_has_exit: exec_type is mixed case in real data
// ('EXIT' but also 'tp_hit', 'stop_hit', 'manual_exit'), so test the
// complement of the entry types rather than enumerating exit types.
function _tradeHasExit(trade) {
  return (trade.executions || []).some(e => {
    const t = String(e.exec_type || '').toUpperCase();
    return t !== 'OPEN' && t !== 'ADD';
  });
}
```

If the executions array on the trade object is not `trade.executions`, find the real name by
reading how `_dynExecsNewestFirst` reads it (`live_v2.html:7165`) and use that.

- [ ] **Step 2: Render the Target cell**

Inside `buildTransactionFeed`, immediately after the `riskCell` assignment in the `isEntry`
branch (`live_v2.html:7196`), add:

```js
          const hasExit = _tradeHasExit(trade);
          const tgtVal = (e.target_price != null && e.target_price !== '') ? Number(e.target_price) : '';
          const tgtCaptured = String(e.target_source || 'none') !== 'none';
          if (hasExit) {
            targetCell = `<span class="feed-stop-wrap">
              <span class="feed-target-locked">${tgtVal === '' ? '—' : tgtVal.toFixed(2)}</span>
              <span class="feed-target-icon locked" title="locked at first exit">&#128274;</span>
            </span>`;
          } else {
            const icon = tgtCaptured
              ? `<span class="feed-target-icon captured" title="planned exit recorded">&#10003;</span>`
              : `<span class="feed-target-icon none" title="no planned exit recorded">&#9679;</span>`;
            targetCell = `<span class="feed-stop-wrap">
              <input class="feed-stop-input" type="number" step="0.25" value="${tgtVal}"
                     onchange="dynEditTrancheTarget(${trade.id}, ${e.id}, this.value)"
                     title="Planned exit for this entry">
              ${icon}
            </span>`;
          }
```

Declare `targetCell` alongside `stopCell` and `riskCell` (`live_v2.html:7182`):

```js
        let stopCell, riskCell, targetCell;
```

And in the `else` branch for exit rows (`live_v2.html:7199`), add:

```js
          targetCell = `<span class="feed-inert">—</span>`;
```

There is deliberately **no pull chip** on the target cell. Working stops are a legitimate
source for "what am I risking"; working TPs are not a legitimate source for "what did I plan",
because they move mid-trade.

- [ ] **Step 3: Place the cell in the row**

In the row template (`live_v2.html:7204-7212`), insert `${targetCell}` between `${stopCell}`
and `${riskCell}`:

```js
          ${stopCell}
          ${targetCell}
          ${riskCell}
```

- [ ] **Step 4: Add the column header**

At `live_v2.html:7237`, add a `Target` header between `Stop` and `Risk`:

```html
    <span>Time</span><span>Type</span><span>Qty</span><span>Price</span><span>Stop</span><span>Target</span><span>Risk</span><span>P&amp;L</span><span style="text-align:right;">Open</span>
```

Then find the CSS grid that lays out `.dyn-feed-cols` and `.dyn-feed-row` (search
`grep -n "dyn-feed-cols" templates/live_v2.html` and read its `grid-template-columns`) and add
one more column track matching the existing Stop track width. The header and row grids must
stay identical or every column after Target will be misaligned.

- [ ] **Step 5: Extend the footer with reward and the no-target note**

Replace the footer accumulation block (`live_v2.html:7216-7223`):

```js
  const entryExecs = execs.filter(e => ['OPEN', 'ADD'].includes(String(e.exec_type || '').toUpperCase()));
  let coreRisk = 0, addRisk = 0, defaultCount = 0, noTargetCount = 0;
  let rewardTotal = 0, targetQty = 0;
  const pvFeed = trade.tickValue || 5;   // same accessor _trancheRisk uses
  entryExecs.forEach(e => {
    const r = _trancheRisk(trade, e) || 0;
    if (String(e.exec_type || '').toUpperCase() === 'OPEN') coreRisk += r; else addRisk += r;
    if (String(e.stop_source || 'default') === 'default') defaultCount++;
    if (e.target_price == null || e.target_price === '') {
      noTargetCount++;
    } else {
      const pts = trade.direction === 'Long'
        ? Number(e.target_price) - Number(e.price)
        : Number(e.price) - Number(e.target_price);
      rewardTotal += pts * Number(e.qty) * pvFeed;
      targetQty += Number(e.qty);
    }
  });
  const ideaRisk = coreRisk + addRisk;
  const rrStr = (targetQty > 0 && ideaRisk > 0)
    ? ` · ${(rewardTotal / ideaRisk).toFixed(1)}R` : '';
```

Then in the footer template (`live_v2.html:7224-7231`), add after the breakdown span:

```js
    ${targetQty > 0 ? `<span class="ir-breakdown">target ${_fmtRisk(rewardTotal)}${rrStr}</span>` : ''}
    ${noTargetCount ? `<span class="ir-default-note">${noTargetCount} entr${noTargetCount !== 1 ? 'ies' : 'y'} with no planned exit</span>` : ''}
```

- [ ] **Step 6: Add the edit function**

Directly after `dynEditTrancheStop` (`live_v2.html:7256`):

```js
/* Planned exit: editable until the first exit, then frozen server-side (409). */
async function dynEditTrancheTarget(tradeId, execId, value) {
  const price = parseFloat(value);
  if (isNaN(price)) return;
  try {
    const res = await fetch(`/api/live/${tradeId}/execution/${execId}/target`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_price: price })
    });
    if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.error || 'Failed'); }
    await refreshTradeFromServer(tradeId);
  } catch (e) {
    if (typeof showToast === 'function') showToast(e.message || 'Target update failed', true);
  }
}
```

- [ ] **Step 7: Add the cell styles**

Next to the existing `.feed-stop-icon` rules (find with
`grep -n "feed-stop-icon" templates/live_v2.html`), add:

```css
.feed-target-icon { font-size: 9px; margin-left: 3px; }
.feed-target-icon.captured { color: var(--mint, #4fffb0); }
.feed-target-icon.none { color: #ffb347; }
.feed-target-icon.locked { color: var(--muted); }
.feed-target-locked { font-family: var(--font-mono); font-size: 11px; color: var(--text); }
```

- [ ] **Step 8: Manual verification — column renders and edits**

Run `python3 server.py`, open a trade with no exits yet, go to MANAGE.

1. The Transactions ledger shows a `Target` column between Stop and Risk, and every column
   after it stays aligned with its header.
2. The OPEN row shows the target you entered with a mint check, or an amber dot if blank.
3. Type a new target into the cell and tab out. The value persists after the row refreshes.
4. The footer reads `Idea Risk $398 · core $398 · add $0 · target $675 · 1.7R`.
5. Clear a target on a second entry — the footer gains
   `1 entry with no planned exit` in amber.

- [ ] **Step 9: Manual verification — the freeze engages**

1. Exit part of the trade (any exit).
2. Return to MANAGE. The Target cells are now static text with a lock icon, not inputs.
3. Confirm the server refuses a bypass:

```bash
python3 -c "
import database as db
with db.get_conn() as c:
    r = c.execute(\"SELECT id, live_trade_id FROM live_trade_executions WHERE UPPER(exec_type)='OPEN' ORDER BY id DESC LIMIT 1\").fetchone()
    print('live_id', r['live_trade_id'], 'exec_id', r['id'])
"
```

Then with those two ids:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH \
  -H 'Content-Type: application/json' -d '{"target_price": 9999}' \
  http://127.0.0.1:5050/api/live/<live_id>/execution/<exec_id>/target
```

Expected: `409`. Re-run the SELECT and confirm `target_price` is unchanged.

- [ ] **Step 10: Commit**

```bash
git add templates/live_v2.html
git commit -m "feat: Target column in the Manage ledger, frozen at first exit

No pull chip on the target: working TPs move mid-trade, so pulling from
them would retro-fit the plan to the outcome. The client lock mirrors
db.live_trade_has_exit; the server 409 is the actual enforcement."
```

---

## Task 7: Peak price — schema, database layer, route

Journal-side only. Nothing here touches `live_trades` or the live flow.

**Files:**
- Modify: `database.py` (migration in `init_db`; new functions)
- Modify: `server.py` (new route after `server.py:486`)
- Modify: `SCHEMA.md`
- Create: `tests/test_peak_capture.py`

**Interfaces:**
- Consumes: `tmp_db`, `client`, `day_id` fixtures (Task 1).
- Produces:
  - `db.set_trade_mfe(trade_id, mfe_price, mfe_timing, mfe_window_minutes) -> None`
  - `db.get_trades_missing_mfe(account_id, on_or_before_date, limit=50) -> list[dict]`
  - `POST /api/trade/<trade_id>/mfe` accepting `{"mfe_price": float, "mfe_timing": "during"|"after"}`
  - `logic.get_mfe_window_minutes() -> int` (default 30, from `app_config`)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_peak_capture.py`:

```python
import database as db
import app_logic as logic


def _trade(day_id, num=1, direction="Long", entry=7715.0, exit_=7731.0, pnl=240.0):
    return db.insert_trade(day_id, num, direction, 3, entry, exit_, pnl, "17:32", "18:02")


def test_mfe_columns_exist(tmp_db):
    with db.get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()]
    assert "mfe_price" in cols
    assert "mfe_timing" in cols
    assert "mfe_window_minutes" in cols


def test_mfe_migration_is_rerunnable(tmp_db):
    db.init_db()
    db.init_db()
    with db.get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()]
    assert cols.count("mfe_price") == 1


def test_no_mfe_source_column(tmp_db):
    """mfe_price IS NULL already means 'not observed'; a source column would be
    redundant state to keep in sync."""
    with db.get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()]
    assert "mfe_source" not in cols


def test_set_trade_mfe_stores_all_three(tmp_db, day_id):
    trade_id = _trade(day_id)
    db.set_trade_mfe(trade_id, 7772.0, "during", 30)
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT mfe_price, mfe_timing, mfe_window_minutes FROM trades WHERE id = ?",
            (trade_id,)).fetchone()
    assert row["mfe_price"] == 7772.0
    assert row["mfe_timing"] == "during"
    assert row["mfe_window_minutes"] == 30


def test_default_mfe_window_is_30(tmp_db):
    assert logic.get_mfe_window_minutes() == 30


def test_mfe_window_reads_from_config(tmp_db):
    db.set_config("mfe_window_minutes", "45")
    assert logic.get_mfe_window_minutes() == 45


def test_mfe_window_falls_back_when_config_is_junk(tmp_db):
    db.set_config("mfe_window_minutes", "not a number")
    assert logic.get_mfe_window_minutes() == 30


def test_post_mfe_stamps_the_window_server_side(client, tmp_db, day_id):
    trade_id = _trade(day_id)
    res = client.post(f"/api/trade/{trade_id}/mfe",
                      json={"mfe_price": 7772.0, "mfe_timing": "after",
                            "mfe_window_minutes": 999})
    assert res.status_code == 200
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT mfe_price, mfe_timing, mfe_window_minutes FROM trades WHERE id = ?",
            (trade_id,)).fetchone()
    assert row["mfe_price"] == 7772.0
    assert row["mfe_timing"] == "after"
    assert row["mfe_window_minutes"] == 30, "client-supplied window must be ignored"


def test_post_mfe_rejects_bad_timing(client, tmp_db, day_id):
    trade_id = _trade(day_id)
    res = client.post(f"/api/trade/{trade_id}/mfe",
                      json={"mfe_price": 7772.0, "mfe_timing": "sometime"})
    assert res.status_code == 400


def test_post_mfe_rejects_missing_price(client, tmp_db, day_id):
    trade_id = _trade(day_id)
    res = client.post(f"/api/trade/{trade_id}/mfe", json={"mfe_timing": "during"})
    assert res.status_code == 400


def test_peak_is_overwritable_unlike_the_target(client, tmp_db, day_id):
    """A peak is a checkable fact about the market, not a record of intent, so
    a wrong value should be fixable. Deliberately unlike the target freeze."""
    trade_id = _trade(day_id)
    client.post(f"/api/trade/{trade_id}/mfe",
                json={"mfe_price": 7772.0, "mfe_timing": "during"})
    res = client.post(f"/api/trade/{trade_id}/mfe",
                      json={"mfe_price": 7780.0, "mfe_timing": "after"})
    assert res.status_code == 200
    with db.get_conn() as conn:
        row = conn.execute("SELECT mfe_price, mfe_timing FROM trades WHERE id = ?",
                           (trade_id,)).fetchone()
    assert row["mfe_price"] == 7780.0
    assert row["mfe_timing"] == "after"


def test_get_trades_missing_mfe_excludes_filled_and_open_trades(tmp_db, day_id):
    filled = _trade(day_id, num=1)
    missing = _trade(day_id, num=2)
    db.set_trade_mfe(filled, 7772.0, "during", 30)

    rows = db.get_trades_missing_mfe(None, "2026-09-01")
    ids = [r["id"] for r in rows]
    assert missing in ids
    assert filled not in ids
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_peak_capture.py -v`
Expected: FAIL — missing columns, and `AttributeError` on `set_trade_mfe`.

- [ ] **Step 3: Add the migration**

In `database.py` `init_db()`, after the target migration added in Task 2:

```python
        # Migration: peak price (max favourable excursion) recorded by hand after
        # the fact. Journal-side only. mfe_timing says whether the peak came
        # before or after the exit, which is what separates "froze at the target"
        # from "left just before it worked". No source column: mfe_price IS NULL
        # already means not observed.
        trade_cols = [r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()]
        if "mfe_price" not in trade_cols:
            conn.execute("ALTER TABLE trades ADD COLUMN mfe_price REAL")
        if "mfe_timing" not in trade_cols:
            conn.execute("ALTER TABLE trades ADD COLUMN mfe_timing TEXT")
        if "mfe_window_minutes" not in trade_cols:
            conn.execute("ALTER TABLE trades ADD COLUMN mfe_window_minutes INTEGER")
```

- [ ] **Step 4: Add the DB functions**

Near `update_trade_notes` (`database.py:1140`):

```python
def set_trade_mfe(trade_id, mfe_price, mfe_timing, mfe_window_minutes):
    """Record the peak price observed around a trade. Overwritable by design:
    unlike the planned exit this is a checkable fact, not a record of intent."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE trades SET mfe_price = ?, mfe_timing = ?, mfe_window_minutes = ? "
            "WHERE id = ?",
            (mfe_price, mfe_timing, mfe_window_minutes, trade_id)
        )


def get_trades_missing_mfe(account_id, on_or_before_date, limit=50):
    """Closed trades with no peak recorded, newest first. Winners and losers
    alike — on a stopped-out trade the peak reveals give-back, which is
    invisible in P&L."""
    wheres = ["t.is_open = 0", "t.mfe_price IS NULL", "d.date <= ?"]
    params = [on_or_before_date]
    if account_id:
        wheres.append("d.account_id = ?")
        params.append(int(account_id))
    params.append(int(limit))
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT t.*, d.date AS date, d.id AS day_id_ref
            FROM trades t
            JOIN trading_days d ON d.id = t.day_id
            WHERE {' AND '.join(wheres)}
            ORDER BY d.date DESC, t.trade_num DESC
            LIMIT ?
        """, params).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 5: Add the config accessor**

In `app_logic.py`, near the other constants (after `INSTRUMENT_CONFIG` at `app_logic.py:621`):

```python
# Peak-price capture window: how far past the exit to look for the best price.
# 30 rather than 60 because a 60-minute window on a short intraday trade
# measures a different trade than the one that was taken.
DEFAULT_MFE_WINDOW_MINUTES = 30


def get_mfe_window_minutes():
    try:
        return int(float(db.get_config("mfe_window_minutes", DEFAULT_MFE_WINDOW_MINUTES)))
    except (TypeError, ValueError):
        return DEFAULT_MFE_WINDOW_MINUTES
```

- [ ] **Step 6: Add the route**

In `server.py`, directly after `api_save_notes` (ends `server.py:486`):

```python
@app.route("/api/trade/<int:trade_id>/mfe", methods=["POST"])
def api_save_trade_mfe(trade_id):
    """Record the peak price the market offered around a trade.

    The window is stamped server-side from config, never taken from the client,
    so every row records the window it was actually measured against.
    """
    body = request.get_json(silent=True) or {}
    if body.get("mfe_price") in (None, ""):
        return jsonify({"error": "mfe_price is required"}), 400
    try:
        mfe_price = float(body["mfe_price"])
    except (TypeError, ValueError):
        return jsonify({"error": "mfe_price must be a number"}), 400
    timing = body.get("mfe_timing")
    if timing not in ("during", "after"):
        return jsonify({"error": "mfe_timing must be 'during' or 'after'"}), 400
    db.set_trade_mfe(trade_id, mfe_price, timing, logic.get_mfe_window_minutes())
    return jsonify({"ok": True})
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_peak_capture.py -v`
Expected: all pass.

- [ ] **Step 8: Update `SCHEMA.md`**

In section `### 3. TRADES`, add three rows:

```
| mfe_price          | REAL    | Nullable. Peak price the market offered from entry through exit + mfe_window_minutes. NULL means not observed. |
| mfe_timing         | TEXT    | Nullable. 'during' (peak came before the exit) \| 'after' (peak came after the exit). |
| mfe_window_minutes | INTEGER | Nullable. The window this observation was measured against, stamped at write time from app_config key `mfe_window_minutes` (default 30). |
```

Then add below the table:

```
> Recorded by hand after the fact — this app has no price feed. `mfe_timing` is what separates
> "the target was reached and not taken" from "the target was reached only after the exit",
> a distinction planned-vs-actual prices cannot make on their own. The window is stored per
> observation so retuning the config leaves existing rows interpretable. No source column:
> `mfe_price IS NULL` already means not observed.
```

- [ ] **Step 9: Run the full suite**

Run: `python3 -m pytest tests/ -v`
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add database.py app_logic.py server.py SCHEMA.md tests/test_peak_capture.py
git commit -m "feat: record peak price (MFE) per journal trade

Adds mfe_price, mfe_timing and mfe_window_minutes to trades, plus the
POST /api/trade/<id>/mfe route. The window is stamped server-side from
config so every row records what it was measured against. Deliberately
overwritable, unlike the planned exit: a peak is a checkable fact about
the market, not a record of intent."
```

---

## Task 8: Derivation layer

The analytical core. Everything here is a pure function over stored values, unit-tested, and
consumed by both remaining UI tasks. Nothing computed is stored.

**Files:**
- Modify: `database.py` (one new batched query)
- Modify: `app_logic.py` (constants and derivation functions)
- Create: `tests/test_plan_analysis.py`

**Interfaces:**
- Consumes: target columns (Task 2), peak columns (Task 7), `get_instrument_config()` (`app_logic.py:660`).
- Produces:
  - `db.get_entry_fills_for_trades(trade_ids) -> dict[int, list[dict]]`
  - `logic.PLAN_EPSILON = 0.25`, `logic.DEFAULT_PLAN_CAPTURE_BAND = 0.10`
  - `logic.get_plan_capture_band() -> float`
  - `logic.weighted_plan_price(entry_fills, key) -> float | None`
  - `logic.compute_capture(direction, avg_entry, avg_exit, target) -> float | None`
  - `logic.classify_bucket(capture, band=None) -> str`
  - `logic.classify_verdict(bucket, direction, target, mfe_price, mfe_timing) -> str | None`
  - `logic.compute_excursion(direction, qty, instrument, avg_exit, mfe_price, mfe_timing) -> dict | None`
  - `logic.build_plan_execution(trades) -> {"rows": [...], "summary": {...}}`

  Bucket values: `'stopped'`, `'cut_early'`, `'at_plan'`, `'ran_past'`, `'no_plan'`.
  Verdict values: `'froze_at_target'`, `'bailed_early'`, `'market_didnt_pay'`, or `None`.
  Excursion kinds: `'give_back'`, `'missed_run'`.

- [ ] **Step 1: Write the failing tests for the primitives**

Create `tests/test_plan_analysis.py`:

```python
import json

import database as db
import app_logic as logic


# ── weighted_plan_price ──────────────────────────────────────────────────────

def test_weighted_plan_price_weights_by_qty():
    fills = [{"qty": 3, "target_price": 7760.0}, {"qty": 2, "target_price": 7770.0}]
    assert logic.weighted_plan_price(fills, "target_price") == 7764.0


def test_weighted_plan_price_ignores_rows_without_a_value():
    """A trade targeted on the core but not the add still yields an honest number."""
    fills = [{"qty": 3, "target_price": 7760.0}, {"qty": 2, "target_price": None}]
    assert logic.weighted_plan_price(fills, "target_price") == 7760.0


def test_weighted_plan_price_is_none_when_nothing_is_set():
    fills = [{"qty": 3, "target_price": None}, {"qty": 2, "target_price": None}]
    assert logic.weighted_plan_price(fills, "target_price") is None


def test_weighted_plan_price_handles_an_empty_list():
    assert logic.weighted_plan_price([], "target_price") is None


# ── compute_capture ──────────────────────────────────────────────────────────

def test_capture_on_a_long_cut_short():
    # planned 45 pts (7715 -> 7760), captured 16.25
    c = logic.compute_capture("Long", 7715.0, 7731.25, 7760.0)
    assert round(c, 4) == 0.3611


def test_capture_is_symmetric_for_shorts():
    c = logic.compute_capture("Short", 7760.0, 7743.75, 7715.0)
    assert round(c, 4) == 0.3611


def test_capture_is_one_when_the_exit_lands_on_the_plan():
    assert logic.compute_capture("Long", 7715.0, 7760.0, 7760.0) == 1.0


def test_capture_exceeds_one_when_held_past_the_plan():
    c = logic.compute_capture("Long", 7715.0, 7770.0, 7760.0)
    assert c > 1.0


def test_capture_is_negative_on_a_loss():
    c = logic.compute_capture("Long", 7715.0, 7688.5, 7760.0)
    assert c < 0


def test_capture_is_none_without_a_target():
    assert logic.compute_capture("Long", 7715.0, 7731.0, None) is None


def test_capture_is_none_when_target_is_within_a_tick_of_entry():
    """A target 0.1 points from entry is not a plan; guard the denominator."""
    assert logic.compute_capture("Long", 7715.0, 7731.0, 7715.1) is None


# ── classify_bucket ──────────────────────────────────────────────────────────

def test_bucket_boundaries_with_the_default_band():
    b = 0.10
    assert logic.classify_bucket(None, b) == "no_plan"
    assert logic.classify_bucket(-0.5, b) == "stopped"
    assert logic.classify_bucket(0.0, b) == "stopped"
    assert logic.classify_bucket(0.01, b) == "cut_early"
    assert logic.classify_bucket(0.8999, b) == "cut_early"
    assert logic.classify_bucket(0.90, b) == "at_plan"
    assert logic.classify_bucket(1.00, b) == "at_plan"
    assert logic.classify_bucket(1.10, b) == "at_plan"
    assert logic.classify_bucket(1.1001, b) == "ran_past"


def test_band_is_configurable(tmp_db):
    db.set_config("plan_capture_band", "0.25")
    assert logic.get_plan_capture_band() == 0.25
    assert logic.classify_bucket(0.80) == "at_plan"


def test_band_falls_back_when_config_is_junk(tmp_db):
    db.set_config("plan_capture_band", "")
    assert logic.get_plan_capture_band() == 0.10


# ── classify_verdict ─────────────────────────────────────────────────────────

def test_verdict_froze_when_the_target_was_reached_before_the_exit():
    v = logic.classify_verdict("cut_early", "Long", 7760.0, 7772.0, "during")
    assert v == "froze_at_target"


def test_verdict_bailed_when_the_target_was_reached_after_the_exit():
    v = logic.classify_verdict("cut_early", "Long", 7760.0, 7772.0, "after")
    assert v == "bailed_early"


def test_verdict_market_didnt_pay_when_the_peak_never_reached_the_target():
    v = logic.classify_verdict("cut_early", "Long", 7760.0, 7750.0, "after")
    assert v == "market_didnt_pay"


def test_verdict_counts_a_peak_exactly_at_the_target_as_offered():
    v = logic.classify_verdict("cut_early", "Long", 7760.0, 7760.0, "during")
    assert v == "froze_at_target"


def test_verdict_is_direction_aware_for_shorts():
    # short target 7715; a peak of 7700 is BETTER than the target
    assert logic.classify_verdict("cut_early", "Short", 7715.0, 7700.0, "during") == "froze_at_target"
    assert logic.classify_verdict("cut_early", "Short", 7715.0, 7730.0, "during") == "market_didnt_pay"


def test_verdict_is_none_without_a_peak():
    assert logic.classify_verdict("cut_early", "Long", 7760.0, None, None) is None


def test_verdict_only_applies_to_cut_early():
    assert logic.classify_verdict("at_plan", "Long", 7760.0, 7772.0, "during") is None
    assert logic.classify_verdict("ran_past", "Long", 7760.0, 7772.0, "during") is None
    assert logic.classify_verdict("stopped", "Long", 7760.0, 7772.0, "during") is None


# ── exit_tag_signals ─────────────────────────────────────────────────────────

def test_tag_conflict_when_tagged_target_hit_but_peak_never_reached_it():
    sig = logic.exit_tag_signals(["Target hit"], False)
    assert sig["conflict"] is True


def test_tag_conflict_when_tagged_never_reached_but_peak_did_reach_it():
    sig = logic.exit_tag_signals(["Target never reached"], True)
    assert sig["conflict"] is True


def test_no_tag_conflict_when_tag_and_peak_agree():
    assert logic.exit_tag_signals(["Target hit"], True)["conflict"] is False
    assert logic.exit_tag_signals(["Target never reached"], False)["conflict"] is False


def test_tag_is_suggested_when_none_was_applied_and_the_target_was_never_offered():
    assert logic.exit_tag_signals([], False)["suggestion"] == "Target never reached"


def test_no_suggestion_when_a_tag_already_exists():
    assert logic.exit_tag_signals(["Fear / Anxious"], False)["suggestion"] is None


def test_no_tag_signals_without_a_peak():
    sig = logic.exit_tag_signals(["Target hit"], None)
    assert sig == {"conflict": False, "suggestion": None}


# ── compute_excursion ────────────────────────────────────────────────────────

def test_excursion_during_is_give_back(tmp_db):
    e = logic.compute_excursion("Long", 3, "MES", 7731.25, 7772.0, "during")
    assert e["kind"] == "give_back"
    assert e["points"] == 40.75
    assert e["dollars"] == 611.25  # 40.75 * 3 * $5


def test_excursion_after_is_missed_run(tmp_db):
    e = logic.compute_excursion("Long", 3, "MES", 7731.25, 7772.0, "after")
    assert e["kind"] == "missed_run"


def test_excursion_is_direction_aware(tmp_db):
    e = logic.compute_excursion("Short", 3, "MES", 7743.75, 7700.0, "during")
    assert e["points"] == 43.75
    assert e["dollars"] == 656.25


def test_excursion_uses_the_instrument_point_value(tmp_db):
    e = logic.compute_excursion("Long", 1, "ES", 7731.0, 7741.0, "after")
    assert e["dollars"] == 500.0  # 10 pts * 1 * $50


def test_excursion_is_none_without_a_peak(tmp_db):
    assert logic.compute_excursion("Long", 3, "MES", 7731.0, None, None) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_plan_analysis.py -v`
Expected: FAIL — `AttributeError: module 'app_logic' has no attribute 'weighted_plan_price'`.

- [ ] **Step 3: Implement the primitives**

In `app_logic.py`, after `get_mfe_window_minutes` (added in Task 7):

```python
# ── Plan vs execution derivation ─────────────────────────────────────────────
# Everything below is derived on read from stored prices. Nothing is persisted.

# A target within one tick of entry is not a plan; it would also blow up the
# capture denominator.
PLAN_EPSILON = 0.25

# Tolerance around 1.0 that still counts as "exited at plan".
DEFAULT_PLAN_CAPTURE_BAND = 0.10


def get_plan_capture_band():
    try:
        return float(db.get_config("plan_capture_band", DEFAULT_PLAN_CAPTURE_BAND))
    except (TypeError, ValueError):
        return DEFAULT_PLAN_CAPTURE_BAND


def _dir_sign(direction):
    """+1 for a long, -1 for a short. trades.direction is 'Long'/'Short'."""
    return 1 if str(direction or "").strip().upper().startswith("L") else -1


def _trade_instrument(trade):
    """Instrument lives in trades.execution_json for journal trades."""
    raw = trade.get("execution_json")
    if not raw:
        return "MES"
    try:
        return (json.loads(raw) or {}).get("instrument") or "MES"
    except (ValueError, TypeError, AttributeError):
        return "MES"


def weighted_plan_price(entry_fills, key):
    """Qty-weighted average of `key` across entry fills that carry a value.

    Rows with NULL are skipped rather than treated as zero, so a trade planned
    on the core but not the add still yields an honest number.
    """
    num = den = 0.0
    for f in entry_fills or []:
        v = f.get(key)
        if v is None:
            continue
        try:
            q = float(f.get("qty") or 0)
        except (TypeError, ValueError):
            continue
        if q <= 0:
            continue
        num += float(v) * q
        den += q
    return (num / den) if den else None


def plan_is_partial(entry_fills):
    """True when some entry rows carry a target and others do not."""
    rows = list(entry_fills or [])
    have = sum(1 for f in rows if f.get("target_price") is not None)
    return 0 < have < len(rows)


def compute_capture(direction, avg_entry, avg_exit, target):
    """Share of the planned move actually taken. 1.0 == exited exactly at plan."""
    if target is None or avg_entry is None or avg_exit is None:
        return None
    sign = _dir_sign(direction)
    planned = sign * (float(target) - float(avg_entry))
    if abs(planned) < PLAN_EPSILON:
        return None
    return (sign * (float(avg_exit) - float(avg_entry))) / planned


def classify_bucket(capture, band=None):
    b = get_plan_capture_band() if band is None else float(band)
    if capture is None:
        return "no_plan"
    if capture <= 0:
        return "stopped"
    if capture < 1 - b:
        return "cut_early"
    if capture <= 1 + b:
        return "at_plan"
    return "ran_past"


def target_was_offered(direction, target, mfe_price):
    """Did the recorded peak ever reach the planned exit?"""
    if target is None or mfe_price is None:
        return None
    return _dir_sign(direction) * (float(mfe_price) - float(target)) >= 0


def classify_verdict(bucket, direction, target, mfe_price, mfe_timing):
    """Three-way split of cut_early using the recorded peak.

    Returns None when there is no peak — the bucket then stands on its own,
    coarse but never wrong.
    """
    if bucket != "cut_early":
        return None
    if mfe_price is None or target is None or mfe_timing not in ("during", "after"):
        return None
    if not target_was_offered(direction, target, mfe_price):
        return "market_didnt_pay"
    return "froze_at_target" if mfe_timing == "during" else "bailed_early"


def exit_tag_signals(exit_tags, target_offered):
    """Reconcile the recorded exit tag against what the peak says was available.

    The peak always wins for classification — nothing here feeds the verdict.
    This only surfaces a disagreement for review rather than silently
    reconciling it, since a disagreement usually means one of the two was
    recorded carelessly. It also suggests the tag the data already implies
    when none was applied.
    """
    if target_offered is None:
        return {"conflict": False, "suggestion": None}
    tags = set(exit_tags or [])
    conflict = (("Target hit" in tags and not target_offered)
                or ("Target never reached" in tags and target_offered))
    suggestion = None
    if not tags and not target_offered:
        suggestion = "Target never reached"
    return {"conflict": conflict, "suggestion": suggestion}


def compute_excursion(direction, qty, instrument, avg_exit, mfe_price, mfe_timing):
    """Distance between the peak and the actual exit, named by when the peak came.

    'during' -> give_back (open profit returned before exiting)
    'after'  -> missed_run (distance travelled without you)
    """
    if mfe_price is None or avg_exit is None or mfe_timing not in ("during", "after"):
        return None
    sign = _dir_sign(direction)
    points = sign * (float(mfe_price) - float(avg_exit))
    inst = get_instrument_config().get(instrument, INSTRUMENT_CONFIG["MES"])
    dpp = inst["dollars_per_point"]
    try:
        q = float(qty or 0)
    except (TypeError, ValueError):
        q = 0.0
    return {
        "kind": "give_back" if mfe_timing == "during" else "missed_run",
        "points": round(points, 2),
        "dollars": round(points * q * dpp, 2),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_plan_analysis.py -v`
Expected: all pass.

- [ ] **Step 5: Commit the primitives**

```bash
git add app_logic.py tests/test_plan_analysis.py
git commit -m "feat: plan-vs-execution derivation primitives

Capture %, bucket classification with a configurable band, the peak-based
three-way verdict split, and give-back/missed-run excursion. All pure
functions over stored prices; nothing computed is persisted."
```

- [ ] **Step 6: Write the failing test for the batched fill query**

Append to `tests/test_plan_analysis.py`:

```python
def _seed_trade(day_id, num, direction, entry, exit_, pnl, entry_fills, instrument="MES"):
    """Insert one journal trade plus its entry and exit fills."""
    qty = sum(f[0] for f in entry_fills)
    trade_id = db.insert_trade(day_id, num, direction, qty, entry, exit_, pnl,
                               "17:32", "18:02",
                               execution_json=json.dumps({"instrument": instrument}))
    entry_side = "Buy" if direction == "Long" else "Sell"
    exit_side = "Sell" if direction == "Long" else "Buy"
    for q, price, stop, target in entry_fills:
        db.insert_fill(trade_id, "17:32", entry_side, q, price,
                       stop_price=stop, stop_source="entered",
                       target_price=target,
                       target_source="none" if target is None else "entered")
    db.insert_fill(trade_id, "18:02", exit_side, qty, exit_, exit_type="manual_exit")
    return trade_id


def test_get_entry_fills_returns_only_entry_side_rows(tmp_db, day_id):
    long_id = _seed_trade(day_id, 1, "Long", 7715.0, 7731.25, 240.0,
                          [(3, 7715.0, 7688.5, 7760.0)])
    short_id = _seed_trade(day_id, 2, "Short", 7760.0, 7743.75, 240.0,
                           [(3, 7760.0, 7788.5, 7715.0)])

    got = db.get_entry_fills_for_trades([long_id, short_id])

    assert len(got[long_id]) == 1
    assert got[long_id][0]["price"] == 7715.0
    assert got[long_id][0]["target_price"] == 7760.0
    # the Short trade's entry fill is the Sell, not the Buy
    assert len(got[short_id]) == 1
    assert got[short_id][0]["price"] == 7760.0


def test_get_entry_fills_handles_an_empty_id_list(tmp_db):
    assert db.get_entry_fills_for_trades([]) == {}
```

- [ ] **Step 7: Run it to verify it fails**

Run: `python3 -m pytest tests/test_plan_analysis.py -k entry_fills -v`
Expected: FAIL — `AttributeError: module 'database' has no attribute 'get_entry_fills_for_trades'`.

- [ ] **Step 8: Implement the batched query**

In `database.py`, after `get_trades_in_range` (ends `database.py:2736`):

```python
def get_entry_fills_for_trades(trade_ids):
    """Entry-side fills for many trades in one query, keyed by trade id.

    An entry fill is a Buy on a Long trade and a Sell on a Short trade —
    trades.direction is 'Long'/'Short' and fills.side is 'Buy'/'Sell'.
    Batched deliberately: the weekly review would otherwise issue one query
    per trade.
    """
    ids = [int(i) for i in (trade_ids or [])]
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    out = {i: [] for i in ids}
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT f.trade_id, f.qty, f.price, f.stop_price, f.stop_source,
                   f.target_price, f.target_source
            FROM fills f
            JOIN trades t ON t.id = f.trade_id
            WHERE f.trade_id IN ({placeholders})
              AND ((t.direction = 'Long'  AND f.side = 'Buy')
                OR (t.direction = 'Short' AND f.side = 'Sell'))
            ORDER BY f.id
        """, ids).fetchall()
        for r in rows:
            out[r["trade_id"]].append(dict(r))
    return out
```

- [ ] **Step 9: Run it to verify it passes**

Run: `python3 -m pytest tests/test_plan_analysis.py -k entry_fills -v`
Expected: 2 passed.

- [ ] **Step 10: Write the failing tests for the assembled payload**

Append to `tests/test_plan_analysis.py`:

```python
def _rows_by_num(result):
    return {r["trade_num"]: r for r in result["rows"]}


def test_build_plan_execution_assembles_rows(tmp_db, day_id):
    _seed_trade(day_id, 1, "Long", 7715.0, 7731.25, 240.0,
                [(3, 7715.0, 7688.5, 7760.0)])
    trades = db.get_trades_in_range(None, "2026-09-01", "2026-09-01")

    result = logic.build_plan_execution(trades)
    row = _rows_by_num(result)[1]

    assert row["target"] == 7760.0
    assert row["stop"] == 7688.5
    assert round(row["capture"], 4) == 0.3611
    assert row["bucket"] == "cut_early"
    assert row["verdict"] is None          # no peak recorded yet
    assert row["excursion"] is None


def test_build_plan_execution_applies_the_peak(tmp_db, day_id):
    tid = _seed_trade(day_id, 1, "Long", 7715.0, 7731.25, 240.0,
                      [(3, 7715.0, 7688.5, 7760.0)])
    db.set_trade_mfe(tid, 7772.0, "during", 30)
    trades = db.get_trades_in_range(None, "2026-09-01", "2026-09-01")

    row = _rows_by_num(logic.build_plan_execution(trades))[1]
    assert row["verdict"] == "froze_at_target"
    assert row["excursion"]["kind"] == "give_back"
    assert row["excursion"]["dollars"] == 611.25
    assert row["target_offered"] is True


def test_build_plan_execution_flags_a_partial_plan(tmp_db, day_id):
    _seed_trade(day_id, 1, "Long", 7715.0, 7731.25, 240.0,
                [(3, 7715.0, 7688.5, 7760.0), (2, 7720.0, 7688.5, None)])
    trades = db.get_trades_in_range(None, "2026-09-01", "2026-09-01")
    row = _rows_by_num(logic.build_plan_execution(trades))[1]
    assert row["partial_plan"] is True
    assert row["target"] == 7760.0


def test_build_plan_execution_marks_untargeted_trades_no_plan(tmp_db, day_id):
    _seed_trade(day_id, 1, "Long", 7715.0, 7731.25, 240.0,
                [(3, 7715.0, 7688.5, None)])
    trades = db.get_trades_in_range(None, "2026-09-01", "2026-09-01")
    result = logic.build_plan_execution(trades)
    assert _rows_by_num(result)[1]["bucket"] == "no_plan"
    assert result["summary"]["no_plan"] == 1


def test_summary_reports_coverage_over_all_trades(tmp_db, day_id):
    a = _seed_trade(day_id, 1, "Long", 7715.0, 7731.25, 240.0,
                    [(3, 7715.0, 7688.5, 7760.0)])
    _seed_trade(day_id, 2, "Long", 7715.0, 7731.25, 240.0,
                [(3, 7715.0, 7688.5, 7760.0)])
    db.set_trade_mfe(a, 7772.0, "during", 30)

    summary = logic.build_plan_execution(
        db.get_trades_in_range(None, "2026-09-01", "2026-09-01"))["summary"]

    assert summary["coverage"]["covered"] == 1
    assert summary["coverage"]["total"] == 2


def test_summary_verdicts_are_counted_over_the_covered_set_only(tmp_db, day_id):
    a = _seed_trade(day_id, 1, "Long", 7715.0, 7731.25, 240.0,
                    [(3, 7715.0, 7688.5, 7760.0)])
    b = _seed_trade(day_id, 2, "Long", 7715.0, 7731.25, 240.0,
                    [(3, 7715.0, 7688.5, 7760.0)])
    _seed_trade(day_id, 3, "Long", 7715.0, 7731.25, 240.0,
                [(3, 7715.0, 7688.5, 7760.0)])   # no peak
    db.set_trade_mfe(a, 7772.0, "during", 30)
    db.set_trade_mfe(b, 7750.0, "after", 30)

    summary = logic.build_plan_execution(
        db.get_trades_in_range(None, "2026-09-01", "2026-09-01"))["summary"]

    assert summary["verdicts"]["froze_at_target"]["count"] == 1
    assert summary["verdicts"]["market_didnt_pay"]["count"] == 1
    assert summary["fear"]["count"] == 1, "market_didnt_pay must not count as fear"


def test_summary_target_realism_uses_the_covered_set(tmp_db, day_id):
    a = _seed_trade(day_id, 1, "Long", 7715.0, 7731.25, 240.0,
                    [(3, 7715.0, 7688.5, 7760.0)])
    b = _seed_trade(day_id, 2, "Long", 7715.0, 7731.25, 240.0,
                    [(3, 7715.0, 7688.5, 7760.0)])
    db.set_trade_mfe(a, 7772.0, "during", 30)   # offered
    db.set_trade_mfe(b, 7750.0, "after", 30)    # never offered

    realism = logic.build_plan_execution(
        db.get_trades_in_range(None, "2026-09-01", "2026-09-01"))["summary"]["realism"]

    assert realism["offered"] == 1
    assert realism["of"] == 2
    assert realism["pct"] == 50.0


def test_summary_survives_a_week_with_no_trades(tmp_db):
    result = logic.build_plan_execution([])
    assert result["rows"] == []
    assert result["summary"]["coverage"] == {"covered": 0, "total": 0}
    assert result["summary"]["realism"]["pct"] is None
```

- [ ] **Step 11: Run them to verify they fail**

Run: `python3 -m pytest tests/test_plan_analysis.py -k "build_plan or summary" -v`
Expected: FAIL — `AttributeError: module 'app_logic' has no attribute 'build_plan_execution'`.

- [ ] **Step 12: Implement the assembly**

In `app_logic.py`, after `compute_excursion`:

```python
_BUCKETS = ("stopped", "cut_early", "at_plan", "ran_past")
_VERDICTS = ("froze_at_target", "bailed_early", "market_didnt_pay")


def build_plan_execution(trades):
    """Per-trade plan-vs-execution rows plus the week roll-up.

    Buckets are computed over every trade that has a target. Verdicts,
    excursion and target realism are computed over the covered set only —
    the trades with a recorded peak — because a percentage over a
    self-selected subset would overstate whatever prompted the filling.
    """
    trades = list(trades or [])
    band = get_plan_capture_band()
    fills_by_trade = db.get_entry_fills_for_trades([t["id"] for t in trades])

    rows = []
    for t in trades:
        fills = fills_by_trade.get(t["id"], [])
        target = weighted_plan_price(fills, "target_price")
        stop = weighted_plan_price(fills, "stop_price")
        capture = compute_capture(t.get("direction"), t.get("avg_entry"),
                                  t.get("avg_exit"), target)
        bucket = classify_bucket(capture, band)
        mfe_price = t.get("mfe_price")
        mfe_timing = t.get("mfe_timing")
        instrument = _trade_instrument(t)
        tags = t.get("tags") or {}
        offered = target_was_offered(t.get("direction"), target, mfe_price)
        tag_signals = exit_tag_signals(tags.get("exit"), offered)
        rows.append({
            "id": t["id"],
            "trade_num": t.get("trade_num"),
            "date": t.get("date"),
            "direction": t.get("direction"),
            "qty": t.get("qty"),
            "pnl": t.get("pnl"),
            "instrument": instrument,
            "avg_entry": t.get("avg_entry"),
            "avg_exit": t.get("avg_exit"),
            "stop": stop,
            "target": target,
            "partial_plan": plan_is_partial(fills),
            "capture": capture,
            "bucket": bucket,
            "mfe_price": mfe_price,
            "mfe_timing": mfe_timing,
            "target_offered": offered,
            "tag_conflict": tag_signals["conflict"],
            "tag_suggestion": tag_signals["suggestion"],
            "verdict": classify_verdict(bucket, t.get("direction"), target,
                                        mfe_price, mfe_timing),
            "excursion": compute_excursion(t.get("direction"), t.get("qty"), instrument,
                                           t.get("avg_exit"), mfe_price, mfe_timing),
            "risk": compute_tranche_risk(t.get("direction"), instrument,
                                         t.get("avg_entry"), stop, t.get("qty") or 0),
            "setup": ", ".join(tags.get("setup", [])) or "—",
            "level": ", ".join(tags.get("with", [])) or "—",
            "exit_tag": ", ".join(tags.get("exit", [])) or "—",
            "notes": t.get("notes") or "",
            "notes_exit": t.get("notes_exit") or "",
        })

    buckets = {k: {"count": 0, "net": 0.0, "captures": []} for k in _BUCKETS}
    verdicts = {k: {"count": 0, "net": 0.0, "captures": []} for k in _VERDICTS}
    no_plan = 0
    give_back = missed_run = 0.0
    offered = of_covered = 0

    for r in rows:
        pnl = float(r["pnl"] or 0)
        if r["bucket"] == "no_plan":
            no_plan += 1
        else:
            b = buckets[r["bucket"]]
            b["count"] += 1
            b["net"] += pnl
            if r["capture"] is not None:
                b["captures"].append(r["capture"])
        if r["verdict"]:
            v = verdicts[r["verdict"]]
            v["count"] += 1
            v["net"] += pnl
            if r["capture"] is not None:
                v["captures"].append(r["capture"])
        if r["excursion"]:
            if r["excursion"]["kind"] == "give_back":
                give_back += r["excursion"]["dollars"]
            else:
                missed_run += r["excursion"]["dollars"]
        if r["target_offered"] is not None:
            of_covered += 1
            if r["target_offered"]:
                offered += 1

    def _finish(d):
        caps = d.pop("captures")
        d["net"] = round(d["net"], 2)
        d["avg_capture"] = round(sum(caps) / len(caps), 4) if caps else None
        return d

    buckets = {k: _finish(v) for k, v in buckets.items()}
    verdicts = {k: _finish(v) for k, v in verdicts.items()}

    covered = sum(1 for r in rows if r["mfe_price"] is not None)
    fear_caps = [r["capture"] for r in rows
                 if r["verdict"] in ("froze_at_target", "bailed_early")
                 and r["capture"] is not None]
    greed_rows = [r for r in rows if r["bucket"] == "ran_past" and float(r["pnl"] or 0) < 0]

    return {
        "rows": rows,
        "summary": {
            "band": band,
            "window_minutes": get_mfe_window_minutes(),
            "buckets": buckets,
            "verdicts": verdicts,
            "no_plan": no_plan,
            "coverage": {"covered": covered, "total": len(rows)},
            "give_back": round(give_back, 2),
            "missed_run": round(missed_run, 2),
            "fear": {
                "count": verdicts["froze_at_target"]["count"] + verdicts["bailed_early"]["count"],
                "net": round(verdicts["froze_at_target"]["net"] + verdicts["bailed_early"]["net"], 2),
                "avg_capture": round(sum(fear_caps) / len(fear_caps), 4) if fear_caps else None,
            },
            "greed": {
                "count": len(greed_rows),
                "net": round(sum(float(r["pnl"] or 0) for r in greed_rows), 2),
            },
            "realism": {
                "offered": offered,
                "of": of_covered,
                "pct": round(offered / of_covered * 100, 1) if of_covered else None,
            },
        },
    }
```

- [ ] **Step 13: Run the full suite**

Run: `python3 -m pytest tests/ -v`
Expected: all pass.

- [ ] **Step 14: Commit**

```bash
git add database.py app_logic.py tests/test_plan_analysis.py
git commit -m "feat: assemble plan-vs-execution rows and weekly roll-up

Buckets span every targeted trade; verdicts, excursion and target realism
span only trades with a recorded peak, and coverage is reported alongside
so percentages are never read as covering the whole week. Entry fills are
fetched in one batched query rather than one per trade."
```

---

## Task 9: PLAN CHECK backfill strip

**Files:**
- Modify: `app_logic.py` (`build_plan_check`)
- Modify: `server.py` (`day_view` render context, `server.py:135-149`)
- Modify: `templates/day.html` (strip markup + JS in the content block, after the breadcrumb at `day.html:227`)
- Test: `tests/test_peak_capture.py`

**Interfaces:**
- Consumes: `db.get_trades_missing_mfe` (Task 7), `db.get_entry_fills_for_trades` and `logic.weighted_plan_price` (Task 8), `POST /api/trade/<id>/mfe` (Task 7).
- Produces: `logic.build_plan_check(day_date, account_id) -> {"today": [...], "earlier": [...], "window_minutes": int}`, passed to the day template as `plan_check`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_peak_capture.py`:

```python
import json


def _seed(day_id, num, target=None, date_hint=None):
    trade_id = db.insert_trade(day_id, num, "Long", 3, 7715.0, 7731.25, 240.0,
                               "17:32", "18:02",
                               execution_json=json.dumps({"instrument": "MES"}))
    db.insert_fill(trade_id, "17:32", "Buy", 3, 7715.0,
                   stop_price=7688.5, stop_source="entered",
                   target_price=target,
                   target_source="none" if target is None else "entered")
    db.insert_fill(trade_id, "18:02", "Sell", 3, 7731.25, exit_type="manual_exit")
    return trade_id


def test_plan_check_splits_today_from_earlier_days(tmp_db):
    today = db.upsert_day("2026-09-02", None)
    yesterday = db.upsert_day("2026-09-01", None)
    t_today = _seed(today, 1, target=7760.0)
    t_earlier = _seed(yesterday, 1, target=7760.0)

    result = logic.build_plan_check("2026-09-02", None)

    assert [r["id"] for r in result["today"]] == [t_today]
    assert [r["id"] for r in result["earlier"]] == [t_earlier]


def test_plan_check_shows_the_weighted_target(tmp_db):
    day = db.upsert_day("2026-09-02", None)
    _seed(day, 1, target=7760.0)
    row = logic.build_plan_check("2026-09-02", None)["today"][0]
    assert row["target"] == 7760.0


def test_plan_check_includes_trades_with_no_target(tmp_db):
    """Losers and unplanned trades still need a peak — give-back is invisible
    in P&L."""
    day = db.upsert_day("2026-09-02", None)
    _seed(day, 1, target=None)
    result = logic.build_plan_check("2026-09-02", None)
    assert len(result["today"]) == 1
    assert result["today"][0]["target"] is None


def test_plan_check_drops_a_trade_once_its_peak_is_recorded(tmp_db):
    day = db.upsert_day("2026-09-02", None)
    tid = _seed(day, 1, target=7760.0)
    assert len(logic.build_plan_check("2026-09-02", None)["today"]) == 1
    db.set_trade_mfe(tid, 7772.0, "during", 30)
    assert logic.build_plan_check("2026-09-02", None)["today"] == []


def test_plan_check_reports_the_window(tmp_db):
    db.upsert_day("2026-09-02", None)
    assert logic.build_plan_check("2026-09-02", None)["window_minutes"] == 30
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/test_peak_capture.py -k plan_check -v`
Expected: FAIL — `AttributeError: module 'app_logic' has no attribute 'build_plan_check'`.

- [ ] **Step 3: Implement `build_plan_check`**

In `app_logic.py`, after `build_plan_execution`:

```python
def build_plan_check(day_date, account_id):
    """Closed trades still missing a peak, split into this day and earlier ones.

    Earlier days are surfaced so a skipped session does not silently vanish —
    an unfilled subset biases every peak-derived percentage in the weekly review.
    """
    pending = db.get_trades_missing_mfe(account_id, day_date)
    fills_by_trade = db.get_entry_fills_for_trades([t["id"] for t in pending])

    today, earlier = [], []
    for t in pending:
        row = {
            "id": t["id"],
            "trade_num": t.get("trade_num"),
            "date": t.get("date"),
            "direction": t.get("direction"),
            "qty": t.get("qty"),
            "pnl": t.get("pnl"),
            "avg_entry": t.get("avg_entry"),
            "avg_exit": t.get("avg_exit"),
            "target": weighted_plan_price(fills_by_trade.get(t["id"], []), "target_price"),
        }
        (today if t.get("date") == day_date else earlier).append(row)

    return {"today": today, "earlier": earlier,
            "window_minutes": get_mfe_window_minutes()}
```

- [ ] **Step 4: Run them to verify they pass**

Run: `python3 -m pytest tests/test_peak_capture.py -k plan_check -v`
Expected: all pass.

- [ ] **Step 5: Pass it to the template**

In `server.py` `day_view`, before the `return render_template(...)` at `server.py:135`:

```python
    plan_check = logic.build_plan_check(day["date"], day.get("account_id"))
```

and add to the `render_template` kwargs:

```python
        plan_check=plan_check,
```

- [ ] **Step 6: Add the strip markup**

In `templates/day.html`, immediately after the breadcrumb div (ends `day.html:227`):

```html
{% if plan_check.today or plan_check.earlier %}
<div class="plan-check" id="plan-check">
  <div class="plan-check-head">
    <span class="pc-title">PLAN CHECK</span>
    <span class="pc-count">{{ plan_check.today|length + plan_check.earlier|length }} trades missing peak</span>
    <span class="pc-hint">best price from entry through exit + {{ plan_check.window_minutes }} min</span>
  </div>

  {% for group, label in [(plan_check.today, ''), (plan_check.earlier, 'earlier days')] %}
    {% if group %}
      {% if label %}<div class="pc-group-label">{{ group|length }} from {{ label }}</div>{% endif %}
      {% for r in group %}
      <div class="pc-row" data-trade="{{ r.id }}">
        <span class="pc-cell pc-num">{% if label %}{{ r.date }} · {% endif %}T{{ r.trade_num }}</span>
        <span class="pc-cell pc-dir {{ 'long' if r.direction == 'Long' else 'short' }}">{{ r.direction|upper }}</span>
        <span class="pc-cell pc-mono">{{ '%.2f'|format(r.avg_entry) }}</span>
        <span class="pc-cell pc-mono">{{ '%.2f'|format(r.avg_exit) }}</span>
        <span class="pc-cell pc-mono pc-target">{% if r.target %}{{ '%.2f'|format(r.target) }}{% else %}—{% endif %}</span>
        <input class="pc-input" type="number" step="0.25" placeholder="peak price"
               id="pc-price-{{ r.id }}">
        <span class="pc-toggle">
          <button type="button" class="pc-tg" data-timing="during" onclick="pcPick({{ r.id }}, 'during')">before exit</button>
          <button type="button" class="pc-tg" data-timing="after"  onclick="pcPick({{ r.id }}, 'after')">after exit</button>
        </span>
        <span class="pc-status" id="pc-status-{{ r.id }}"></span>
      </div>
      {% endfor %}
    {% endif %}
  {% endfor %}
</div>
{% endif %}
```

- [ ] **Step 7: Add the strip styles**

In the `{% block extra_styles %}` block of `day.html` (starts `day.html:4`):

```css
.plan-check { border:1px solid var(--border); border-radius:6px; padding:10px 12px; margin:12px 0; }
.plan-check-head { display:flex; align-items:baseline; gap:10px; margin-bottom:8px; }
.pc-title { font-size:11px; letter-spacing:.08em; color:var(--text); }
.pc-count { font-size:11px; color:#ffb347; }
.pc-hint { font-size:10px; color:var(--muted); margin-left:auto; }
.pc-group-label { font-size:10px; color:var(--muted); margin:8px 0 4px; }
.pc-row { display:flex; align-items:center; gap:8px; padding:4px 0; }
.pc-cell { font-size:11px; color:var(--muted); }
.pc-mono { font-family:var(--font-mono); color:var(--text); }
.pc-dir.long { color:#4fffb0; } .pc-dir.short { color:#ff6b6b; }
.pc-input { width:96px; font-family:var(--font-mono); font-size:11px; padding:3px 6px;
            background:transparent; border:1px solid var(--border); border-radius:3px; color:var(--text); }
.pc-tg { font-size:10px; padding:3px 7px; background:transparent; cursor:pointer;
         border:1px solid var(--border); color:var(--muted); border-radius:3px; }
.pc-tg.active { border-color:#4fffb0; color:#4fffb0; }
.pc-status { font-size:10px; color:#4fffb0; margin-left:auto; }
```

- [ ] **Step 8: Add the strip script**

In the `{% block scripts %}` block of `day.html` (starts `day.html:667`):

```js
/* PLAN CHECK: record the peak price the market offered around each trade.
   Saves on the timing tap, since the price alone is not a complete record. */
async function pcPick(tradeId, timing) {
  const input = document.getElementById('pc-price-' + tradeId);
  const status = document.getElementById('pc-status-' + tradeId);
  const price = parseFloat(input && input.value);
  if (!price || isNaN(price)) {
    if (status) { status.style.color = '#ff6b6b'; status.textContent = 'enter a price first'; }
    if (input) input.focus();
    return;
  }
  const row = document.querySelector('.pc-row[data-trade="' + tradeId + '"]');
  if (row) row.querySelectorAll('.pc-tg').forEach(b => {
    b.classList.toggle('active', b.dataset.timing === timing);
  });
  try {
    const res = await fetch('/api/trade/' + tradeId + '/mfe', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mfe_price: price, mfe_timing: timing })
    });
    if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.error || 'Failed'); }
    if (status) { status.style.color = '#4fffb0'; status.textContent = 'saved'; }
    if (input) input.disabled = true;
  } catch (e) {
    if (status) { status.style.color = '#ff6b6b'; status.textContent = e.message || 'save failed'; }
  }
}
```

- [ ] **Step 9: Manual verification**

1. Run `python3 server.py` and open a day that has closed trades.
2. The `PLAN CHECK` strip appears above the grade tray, with one row per closed trade
   lacking a peak and an accurate `N trades missing peak` count.
3. The hint reads `best price from entry through exit + 30 min`.
4. Click `before exit` **without** typing a price — the row shows `enter a price first`
   in red and nothing is saved.
5. Type a peak price, click `before exit` — the button highlights, the row shows `saved`,
   and the input disables.
6. Reload the page — that trade is gone from the strip and the count has dropped by one.
7. Confirm the stored values:

```bash
python3 -c "
import database as db
with db.get_conn() as c:
    for r in c.execute('SELECT id, mfe_price, mfe_timing, mfe_window_minutes FROM trades WHERE mfe_price IS NOT NULL ORDER BY id DESC LIMIT 3'):
        print(dict(r))
"
```

Expected: `mfe_timing` is `during`, `mfe_window_minutes` is `30`.

8. Open a day from an earlier date with unfilled trades and confirm the
   `N from earlier days` group appears with the date prefixed on each row.

- [ ] **Step 10: Run the full suite**

Run: `python3 -m pytest tests/ -v`
Expected: all pass.

- [ ] **Step 11: Commit**

```bash
git add app_logic.py server.py templates/day.html tests/test_peak_capture.py
git commit -m "feat: PLAN CHECK backfill strip on the day page

One pass at session end records the peak for every closed trade, winners
and losers. Earlier unfilled days are surfaced too: an unfilled subset is
self-selected, and would bias every peak-derived percentage in the weekly
review. Push behaviour is unchanged — the strip blocks nothing."
```

---

## Task 10: Exit tag vocabulary

**Files:**
- Modify: `app_logic.py` (`TAG_GROUPS`, the `exit` group at `app_logic.py:39-46`)
- Test: `tests/test_plan_analysis.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an extended `exit` tag group. Task 11 renders these; nothing depends on the exact strings in code.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_plan_analysis.py`:

```python
def test_exit_tag_vocabulary_covers_the_reasons_the_data_cannot_derive():
    group = next(g for g in logic.TAG_GROUPS if g["id"] == "exit")
    for tag in ("Target hit", "Target never reached", "Stopped out",
                "Greed / chased", "Time stop", "Management error"):
        assert tag in group["tags"], f"missing exit tag: {tag}"
    # the two originals must survive so existing tagged trades stay valid
    assert "Planned — Monitored Continuation" in group["tags"]
    assert "Fear / Anxious" in group["tags"]
    assert group["multi"] is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_plan_analysis.py -k exit_tag -v`
Expected: FAIL with `missing exit tag: Target hit`.

- [ ] **Step 3: Extend the group**

Replace the `exit` group in `TAG_GROUPS` (`app_logic.py:39-46`):

```python
    {
        "id": "exit",
        "label": "Exit",
        "dot": "dot-exit",
        "active_class": "active-exit",
        # Why the exit happened. The recorded peak (mfe_price) now answers what
        # was available, so these carry the reason rather than the verdict.
        # 'Target never reached' is also derivable — keep it for narrative and
        # for trades with no peak recorded.
        "tags": [
            "Planned — Monitored Continuation", "Target hit", "Fear / Anxious",
            "Greed / chased", "Target never reached", "Stopped out",
            "Time stop", "Management error",
        ],
        "multi": False,
    },
```

The two original strings are preserved verbatim — `trade_tags` rows store the tag text, so
renaming either would orphan every already-tagged trade.

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 -m pytest tests/test_plan_analysis.py -k exit_tag -v`
Expected: PASS.

- [ ] **Step 5: Manual verification — existing tags still resolve**

Run `python3 server.py`, open a day with a previously tagged trade, expand the trade tray,
and confirm the Exit group shows the new options with any existing selection still highlighted.

- [ ] **Step 6: Commit**

```bash
git add app_logic.py tests/test_plan_analysis.py
git commit -m "feat: widen the exit tag vocabulary

Six new reasons alongside the two originals, which are preserved verbatim
so already-tagged trades keep resolving. These now carry the reason for
an exit; the recorded peak carries the verdict."
```

---

## Task 11: Weekly PLAN vs EXECUTION section

**Files:**
- Modify: `app_logic.py` (`build_weekly_review_data` return dict, `app_logic.py:2434-2460`)
- Modify: `templates/weekly_review.html` (new zone after the Trade ledger, `weekly_review.html:277`)
- Test: `tests/test_plan_analysis.py`

**Interfaces:**
- Consumes: `logic.build_plan_execution` (Task 8), the widened exit tags (Task 10).
- Produces: `data.plan_execution` in the weekly payload, shape `{"rows": [...], "summary": {...}}` exactly as returned by `build_plan_execution`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_plan_analysis.py`:

```python
def test_weekly_payload_carries_plan_execution(tmp_db):
    day_id = db.upsert_day("2026-08-31", None)   # a Monday
    tid = _seed_trade(day_id, 1, "Long", 7715.0, 7731.25, 240.0,
                      [(3, 7715.0, 7688.5, 7760.0)])
    db.set_trade_mfe(tid, 7772.0, "during", 30)

    data = logic.build_weekly_review_data(None, "2026-08-31")

    assert "plan_execution" in data
    pe = data["plan_execution"]
    assert pe["summary"]["coverage"] == {"covered": 1, "total": 1}
    assert pe["rows"][0]["verdict"] == "froze_at_target"
    assert pe["rows"][0]["tag_conflict"] is False
    assert "tag_suggestion" in pe["rows"][0]


def test_weekly_payload_plan_execution_is_empty_for_a_quiet_week(tmp_db):
    data = logic.build_weekly_review_data(None, "2026-08-31")
    assert data["plan_execution"]["rows"] == []
    assert data["plan_execution"]["summary"]["realism"]["pct"] is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/test_plan_analysis.py -k weekly_payload -v`
Expected: FAIL — `KeyError: 'plan_execution'`.

- [ ] **Step 3: Wire it into the weekly payload**

In `app_logic.py`, in `build_weekly_review_data`, add to the returned dict beside `"ledger"`
(`app_logic.py:2456`):

```python
        "plan_execution": build_plan_execution(trades),
```

`trades` is already in scope from `db.get_trades_in_range` at `app_logic.py:2359`, so this adds
exactly one batched fill query per page render.

- [ ] **Step 4: Run them to verify they pass**

Run: `python3 -m pytest tests/test_plan_analysis.py -k weekly_payload -v`
Expected: PASS.

- [ ] **Step 5: Add the section styles**

In the `<style>` block of `templates/weekly_review.html`, beside the existing `.wr-*` rules:

```css
.wr-pe-bands { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:10px; }
.wr-pe-tile { background:var(--surface2); border:0.5px solid var(--border2); border-radius:6px;
              padding:8px 11px; min-width:104px; }
.wr-pe-tile .lbl { font-size:8.5px; letter-spacing:1px; text-transform:uppercase; color:var(--muted); }
.wr-pe-tile .val { font-family:'JetBrains Mono', monospace; font-size:14px; margin-top:3px; }
.wr-pe-tile .sub { font-size:10px; color:var(--muted2); margin-top:2px; }
.wr-pe-coverage { font-size:10px; color:var(--muted2); margin:10px 0 6px; }
.wr-pe-headline { font-size:12px; color:var(--text); margin:6px 0 10px; line-height:1.5; }
.wr-pe-headline .fear { color:#ff6b6b; } .wr-pe-headline .greed { color:#ffb347; }
.wr-pe-headline .realism { color:var(--muted2); display:block; margin-top:4px; }
.wr-pe-why { font-size:11px; color:var(--muted2); padding:0 8px 8px 8px; border-bottom:0.5px solid var(--border); }
.wr-pe-v { font-size:10px; padding:1px 5px; border-radius:3px; border:0.5px solid var(--border2); }
.wr-pe-v.froze_at_target { color:#ff6b6b; border-color:#ff6b6b; }
.wr-pe-v.bailed_early { color:#ff6b6b; border-color:#ff6b6b; }
.wr-pe-v.market_didnt_pay { color:var(--muted2); }
.wr-pe-partial { font-size:9px; color:#ffb347; margin-left:4px; }
.wr-pe-conflict { font-size:9px; color:#ff6b6b; border:0.5px solid #ff6b6b; border-radius:3px; padding:1px 5px; margin-left:6px; }
.wr-pe-suggest { font-size:9px; color:var(--muted2); border:0.5px solid var(--border2); border-radius:3px; padding:1px 5px; margin-left:6px; }
```

- [ ] **Step 6: Add the section markup**

In `templates/weekly_review.html`, after the Trade ledger block closes (`weekly_review.html:277`)
and before `</div>` of that zone:

```html
    {% set pe = data.plan_execution %}
    {% set s = pe.summary %}
    <div class="wr-sub-title">Plan vs execution</div>
    {% if pe.rows %}

    <div class="wr-pe-bands">
      {% for key, label in [('stopped','Stopped'), ('cut_early','Cut early'), ('at_plan','At plan'), ('ran_past','Ran past')] %}
      <div class="wr-pe-tile">
        <div class="lbl">{{ label }}</div>
        <div class="val {{ 'pos' if s.buckets[key].net >= 0 else 'neg' }}">{{ money(s.buckets[key].net) }}</div>
        <div class="sub">{{ s.buckets[key].count }} trades{% if s.buckets[key].avg_capture is not none %} · {{ '{:.0f}'.format(s.buckets[key].avg_capture * 100) }}%{% endif %}</div>
      </div>
      {% endfor %}
      {% if s.no_plan %}
      <div class="wr-pe-tile"><div class="lbl">No plan</div><div class="val">{{ s.no_plan }}</div><div class="sub">no target set</div></div>
      {% endif %}
    </div>

    <div class="wr-pe-coverage">Peak recorded on {{ s.coverage.covered }} of {{ s.coverage.total }} trades{% if s.coverage.covered < s.coverage.total %} — verdicts below cover only those{% endif %}.</div>

    {% if s.coverage.covered %}
    <div class="wr-pe-bands">
      {% for key, label in [('froze_at_target','Froze at target'), ('bailed_early','Bailed early'), ('market_didnt_pay',"Market didn't pay")] %}
      <div class="wr-pe-tile">
        <div class="lbl">{{ label }}</div>
        <div class="val {{ 'pos' if s.verdicts[key].net >= 0 else 'neg' }}">{{ money(s.verdicts[key].net) }}</div>
        <div class="sub">{{ s.verdicts[key].count }} trades</div>
      </div>
      {% endfor %}
      <div class="wr-pe-tile"><div class="lbl">Give-back</div><div class="val neg">{{ money(s.give_back) }}</div><div class="sub">returned before exit</div></div>
      <div class="wr-pe-tile"><div class="lbl">Missed run</div><div class="val">{{ money(s.missed_run) }}</div><div class="sub">after exit</div></div>
    </div>

    <div class="wr-pe-headline">
      {% if s.fear.count %}
      <span class="fear">{{ s.fear.count }} trade{{ 's' if s.fear.count != 1 }} cut{% if s.fear.avg_capture is not none %} at an average {{ '{:.0f}'.format(s.fear.avg_capture * 100) }}% of plan{% endif %} while the target was on the table.</span>
      {% endif %}
      {% if s.greed.count %}
      <span class="greed">{{ s.greed.count }} trade{{ 's' if s.greed.count != 1 }} held past plan and closed red ({{ money(s.greed.net) }}).</span>
      {% endif %}
      {% if s.realism.pct is not none %}
      <span class="realism">Target was reachable on {{ s.realism.offered }} of {{ s.realism.of }} covered trades ({{ s.realism.pct }}%){% if s.realism.pct < 50 %} — targets may be set too far out, which reads like fear but needs the opposite fix{% endif %}.</span>
      {% endif %}
    </div>
    {% endif %}

    <table class="wr-table">
      <thead><tr>
        <th>Date</th><th>Setup</th><th>Level</th>
        <th class="num">Stop</th><th class="num">Plan</th><th class="num">Actual</th><th class="num">Peak</th>
        <th class="num">Capture</th><th>Verdict</th><th class="num">Size/Risk</th>
      </tr></thead>
      <tbody>
        {% for r in pe.rows %}
        <tr>
          <td>{{ r.date }}</td>
          <td>{{ r.setup }}</td>
          <td>{{ r.level }}</td>
          <td class="num">{% if r.stop %}{{ '%.2f'|format(r.stop) }}{% else %}—{% endif %}</td>
          <td class="num">{% if r.target %}{{ '%.2f'|format(r.target) }}{% if r.partial_plan %}<span class="wr-pe-partial" title="some entries had no target">partial</span>{% endif %}{% else %}—{% endif %}</td>
          <td class="num">{{ '%.2f'|format(r.avg_exit) }}</td>
          <td class="num">{% if r.mfe_price %}{{ '%.2f'|format(r.mfe_price) }} <span class="wr-pe-partial">{{ 'dur' if r.mfe_timing == 'during' else 'aft' }}</span>{% else %}—{% endif %}</td>
          <td class="num">{% if r.capture is not none %}{{ '{:.2f}'.format(r.capture) }}{% else %}—{% endif %}</td>
          <td>{% if r.verdict %}<span class="wr-pe-v {{ r.verdict }}">{{ r.verdict.replace('_', ' ') }}</span>{% else %}{{ r.bucket.replace('_', ' ') }}{% endif %}</td>
          <td class="num">{{ r.qty }}{% if r.risk %} · {{ money(r.risk) }}{% endif %}</td>
        </tr>
        {% if r.notes or r.notes_exit or r.exit_tag != '—' %}
        <tr><td colspan="10" class="wr-pe-why">
          {% if r.notes %}in: {{ r.notes }}{% endif %}
          {% if r.notes and (r.notes_exit or r.exit_tag != '—') %} · {% endif %}
          {% if r.exit_tag != '—' or r.notes_exit %}out: {% if r.exit_tag != '—' %}{{ r.exit_tag }}{% endif %}{% if r.exit_tag != '—' and r.notes_exit %} — {% endif %}{{ r.notes_exit }}{% endif %}
          {% if r.tag_conflict %}<span class="wr-pe-conflict" title="the exit tag disagrees with the recorded peak — one of them was recorded carelessly">tag disagrees with peak</span>{% endif %}
          {% if r.tag_suggestion %}<span class="wr-pe-suggest" title="derived from the peak; not applied automatically">suggests: {{ r.tag_suggestion }}</span>{% endif %}
        </td></tr>
        {% endif %}
        {% endfor %}
      </tbody>
    </table>

    {% else %}<div class="wr-empty">No trades this week.</div>{% endif %}
```

- [ ] **Step 7: Manual verification**

1. Run `python3 server.py`, open `/weekly-review`, navigate to a week with trades.
2. The `Plan vs execution` section renders below the Trade ledger with four bucket tiles.
3. The coverage line reads `Peak recorded on N of M trades.`
4. With no peaks recorded that week, the verdict tiles and headline are **absent**
   (not rendered as zeros) and the table still renders with `—` in the Peak column and the
   plain bucket name in Verdict.
5. Record a peak via the day page PLAN CHECK strip, reload the weekly page: the verdict
   band appears, coverage increments, and that row shows a verdict chip.
6. Navigate to a week with no trades at all — the section shows `No trades this week.`
   and does not raise.

- [ ] **Step 8: Run the full suite**

Run: `python3 -m pytest tests/ -v`
Expected: all pass.

- [ ] **Step 9: Bump the version and changelog**

Set `VERSION` to:

```
4.8.0
```

Prepend to `CHANGELOG.md` below the intro lines:

```markdown
## [4.8.0] — 2026-09-06

### Planned exit capture & Plan-vs-Execution review

Records what was planned, not just what happened, so the weekly review can separate a
disciplined exit from a fearful one.

- **Planned exit per entry decision:** a Target field on the Entry and Add forms and a Target
  column in the Manage ledger, stored alongside the existing per-tranche stop and carried onto
  journal fills on push. Blank is a recorded state (`'none'`) — there is no default target.
- **Frozen at first exit:** targets stop being editable once a trade has any exit, enforced
  server-side with a 409. A target is a record of intent, so editing it after the outcome is
  known would let the review confirm itself.
- **Peak price capture:** a PLAN CHECK strip on the day page records the best price the market
  offered around each trade, plus whether that peak came before or after the exit. Push
  behaviour is unchanged.
- **Plan vs Execution section** on the weekly review: capture % against the plan, bucketed
  (Stopped / Cut early / At plan / Ran past) with a configurable band, and — where a peak was
  recorded — the three-way split of Cut early into froze at target, bailed early, or the market
  never paid. Also reports give-back, missed run, and target realism.
- **Coverage is always shown.** Peak-derived percentages cover only the trades with a recorded
  peak, and the section says so rather than implying they cover the week.
- **Widened exit tag vocabulary:** Target hit, Target never reached, Stopped out,
  Greed / chased, Time stop, Management error.
- **Test suite introduced.** The project previously had none; pytest now covers the schema,
  routes, freeze rule, and all plan-vs-execution derivation.
```

- [ ] **Step 10: Commit and push**

```bash
git add app_logic.py templates/weekly_review.html tests/test_plan_analysis.py CHANGELOG.md VERSION
git commit -m "feat: Plan vs Execution section on the weekly review

Three bands — buckets over every targeted trade, verdicts and excursion
over the covered set only, with coverage stated above them. Target realism
is reported beside the fear headline rather than inside it: targets set too
far out look identical to fear in capture % but need the opposite fix.

Bumps version to 4.8.0."
git push
```

---

## Verification checklist

Run after the final task. Every item must pass before the feature is considered done.

- [ ] `python3 -m pytest tests/ -v` — all pass
- [ ] `git status --short data/` — empty (tests never touched the real journal)
- [ ] `python3 -c "import database as db; db.init_db(); db.init_db(); print('ok')"` — migrations re-run cleanly against the **real** database
- [ ] Open an existing pre-feature trade in the day view — it renders with `—` for target and peak, and raises nothing
- [ ] Weekly review for a week predating the feature — renders with `No plan` counts and no verdict band
- [ ] `grep -rn "TODO\|FIXME" app_logic.py database.py server.py templates/live_v2.html templates/day.html templates/weekly_review.html` — no new markers introduced by this work
