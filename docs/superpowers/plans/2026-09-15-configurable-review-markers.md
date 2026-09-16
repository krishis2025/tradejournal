# Configurable Review Markers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move five hardcoded review vocabularies into editable config, make emotions and process violations multi-select, and give them their own Settings tab.

**Architecture:** Each tag gains a stable `tag_key` the code references plus an editable label the UI shows, both stored in the existing `tag_config` table. Trades store keys, so renaming is free and needs no cascade. `emotion` and `process_violation` become JSON arrays of keys in their existing TEXT columns. Validation reads the configured vocabulary at request time instead of closing over module constants.

**Tech Stack:** Python 3.9.6, Flask, SQLite (stdlib `sqlite3`), Jinja2, vanilla JS. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-15-configurable-review-markers-design.md`

## Global Constraints

- **Python 3.9.6.** No 3.10+ syntax — no `match`, no `X | Y` type unions.
- **Three-layer rule.** SQL only in `database.py`; business logic only in `app_logic.py`; `server.py` routes only.
- **`init_db()` runs on every request** via `@app.before_request`. Every migration must be guarded and re-runnable forever. One-shot data migrations use an `app_config` flag key, following the existing `migration_avg_entry_repaired` pattern.
- **Nothing derived is persisted.**
- **`data/journal.db` is gitignored** and never travels with the code. Never point `DB_PATH` at it — copy first. It is the user's real trading history.
- **Update `SCHEMA.md` whenever the DB schema changes.**
- **Trades store KEYS, never labels.** A label is display-only and may be edited at any time.
- **Locked blocks deletion only.** A locked tag can still be renamed. Preventing *addition* is the separate group-level `fixed_set` property, set on `management` alone.
- **The grade vocabulary (A/B/C) stays a code constant** and is out of scope.
- **Commit straight to main. Never branch, never open a PR. COMMIT ONLY — do NOT push to any remote.**
- **Every new test must be mutation-checked**: reintroduce the bug it guards, watch that specific test fail, restore. Report the observed outcome. In the previous feature five tests shipped that could not fail; four were caught only at review.

## Controller notes

`tag_config` currently stores `(group_id, tag, position, enabled)` where `tag` IS the identity, and `save_tag_config` cascades renames across trades — the source of the 4.8.1 data bug. The five new groups do **not** use that path. They are key-addressed and must never be routed through `save_tag_config` or `_cascade_tag_rename`.

---

### Task 1: Schema, defaults, and the config accessors

**Files:**
- Modify: `database.py` (migration beside the other `ALTER TABLE` guards in `init_db()`; functions near `get_tag_config`, around line 1519)
- Modify: `app_logic.py` (add `REVIEW_MARKER_GROUPS` near the existing vocabularies, around line 537)
- Modify: `SCHEMA.md`
- Test: `tests/test_review_markers.py` (create)

**Interfaces:**
- Produces:
  - `logic.REVIEW_MARKER_GROUPS` — ordered list of group dicts (shape below)
  - `db.get_review_marker_config()` → `{group_id: [{"key","label","locked","at_entry"}, ...]}` or `None` when nothing is configured
  - `db.save_review_marker_group(group_id, tags)` — `tags` is an ordered list of `{"key","label","at_entry"}`
  - `db.get_group_multi(group_id, default)` → bool; `db.set_group_multi(group_id, value)`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_review_markers.py`:

```python
"""Configurable review markers.

Five review vocabularies live in tag_config with a stable key plus an editable
label. Trades store the key, so renaming a label is free — no cascade, no
migration, and none of the 4.8.1 rename/delete ambiguity.
"""
import sqlite3

import app_logic as logic
import database as db


def test_tag_config_gains_key_locked_and_entry_columns(tmp_db):
    cols = {r[1] for r in sqlite3.connect(tmp_db)
            .execute("PRAGMA table_info(tag_config)").fetchall()}

    assert {"tag_key", "locked", "at_entry"} <= cols


def test_defaults_declare_five_groups_with_the_expected_keys():
    groups = {g["id"]: g for g in logic.REVIEW_MARKER_GROUPS}

    assert list(groups) == ["management", "management_driver", "management_issue",
                            "emotion", "process_violation"]
    assert [t["key"] for t in groups["process_violation"]["tags"]] == [
        "none", "traded_outside_plan", "exceeded_risk", "revenge_trade", "overtraded"]
    assert [t["key"] for t in groups["emotion"]["tags"]] == [
        "calm", "fear_of_loss", "fear_of_giving_back", "greed",
        "frustration", "impatience", "overconfidence", "distracted"]


def test_management_is_fixed_set_and_both_options_locked():
    """The code branches on exactly two states, so a third would be unreadable.
    fixed_set blocks the Add box; locked blocks deletion of each option."""
    mgmt = [g for g in logic.REVIEW_MARKER_GROUPS if g["id"] == "management"][0]

    assert mgmt["fixed_set"] is True
    assert all(t["locked"] for t in mgmt["tags"])


def test_the_two_fear_states_are_the_only_ones_off_at_entry():
    """You cannot feel either before you hold a position."""
    emotion = [g for g in logic.REVIEW_MARKER_GROUPS if g["id"] == "emotion"][0]
    off = [t["key"] for t in emotion["tags"] if not t["at_entry"]]

    assert off == ["fear_of_loss", "fear_of_giving_back"]


def test_save_and_read_back_a_group(tmp_db):
    db.save_review_marker_group("process_violation", [
        {"key": "none", "label": "Clean", "at_entry": True},
        {"key": "overtraded", "label": "Overtraded", "at_entry": True},
    ])

    cfg = db.get_review_marker_config()["process_violation"]

    assert [t["key"] for t in cfg] == ["none", "overtraded"]
    assert cfg[0]["label"] == "Clean"


def test_saved_order_is_preserved(tmp_db):
    """Order is the order the chips appear in; it must survive a round trip."""
    db.save_review_marker_group("management_driver", [
        {"key": "pnl", "label": "P&L", "at_entry": True},
        {"key": "both", "label": "Both", "at_entry": True},
        {"key": "market_thesis", "label": "Market / Thesis", "at_entry": True},
    ])

    keys = [t["key"] for t in db.get_review_marker_config()["management_driver"]]

    assert keys == ["pnl", "both", "market_thesis"]


def test_saving_a_group_replaces_rather_than_appends(tmp_db):
    db.save_review_marker_group("management_driver", [
        {"key": "pnl", "label": "P&L", "at_entry": True}])
    db.save_review_marker_group("management_driver", [
        {"key": "both", "label": "Both", "at_entry": True}])

    keys = [t["key"] for t in db.get_review_marker_config()["management_driver"]]

    assert keys == ["both"]


def test_review_marker_rows_never_collide_with_legacy_tag_groups(tmp_db):
    """The five new groups share the tag_config table with the legacy
    label-addressed groups. get_tag_config() feeds the OLD settings cards and
    must not start returning review markers, or Technicals would sprout
    emotions."""
    db.save_review_marker_group("emotion", [
        {"key": "calm", "label": "Calm", "at_entry": True}])

    legacy = db.get_tag_config() or {}

    assert "emotion" not in legacy


def test_deleting_a_tag_does_not_touch_trades_that_used_it(tmp_db, day_id):
    """The 4.8.1 guard, re-pinned for keys.

    That bug came from save_tag_config reading a deletion as a rename — labels
    were identity, so removing one shifted the rest and the cascade relabelled
    11 real trades. Review markers store keys and run no cascade, so removing a
    tag from the vocabulary must leave every trade's stored key exactly as it
    was. The trade then renders via marker_label's key fallback.
    """
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, -50.0, "10:00", "10:30")
    db.set_trade_assessment(trade_id, grade="C", emotion="greed")

    db.save_review_marker_group("emotion", [
        {"key": "calm", "label": "Calm", "at_entry": True},
    ])

    with db.get_conn() as conn:
        stored = conn.execute("SELECT emotion FROM trades WHERE id = ?",
                              (trade_id,)).fetchone()[0]
    assert stored == "greed", "a vocabulary edit must never rewrite trade data"


def test_multi_flag_round_trips_and_defaults(tmp_db):
    assert db.get_group_multi("emotion", True) is True
    assert db.get_group_multi("management", False) is False

    db.set_group_multi("management", True)

    assert db.get_group_multi("management", False) is True
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m pytest tests/test_review_markers.py -q`
Expected: FAIL — missing columns, `AttributeError` on `logic.REVIEW_MARKER_GROUPS` and the four `db.` functions.

- [ ] **Step 3: Add the defaults to `app_logic.py`**

Place near the existing assessment vocabularies. Leave `GRADES`, `MANAGEMENT`, `MANAGEMENT_ISSUES`, `EMOTIONS`, `ENTRY_EMOTIONS`, `PROCESS_VIOLATIONS` and `MANAGEMENT_DRIVERS` in place for now — Task 3 retires them.

```python
# ── Review markers ───────────────────────────────────────────────────────────
# Editable vocabularies for the trade review. Each tag carries a stable `key`
# that trades store and code branches on, plus a `label` the trader may rename
# at will. Because identity is the key, a rename needs no cascade — which is
# also why the 4.8.1 delete-read-as-rename bug cannot occur in these groups.
#
# locked    — the tag cannot be deleted (it may still be renamed)
# fixed_set — the group accepts no new tags at all

REVIEW_MARKER_GROUPS = [
    {
        "id": "management", "label": "How did you manage it?",
        "multi": False, "fixed_set": True, "entry_flag": False,
        "tags": [
            # Relabel-only: the review chain branches on `deviated` to decide
            # whether to ask "What changed?". A third state would be unreadable.
            {"key": "followed", "label": "Followed process", "locked": True, "at_entry": True},
            {"key": "deviated", "label": "Deviated", "locked": True, "at_entry": True},
        ],
    },
    {
        "id": "management_driver", "label": "What primarily drove your management decisions?",
        "multi": False, "fixed_set": False, "entry_flag": False,
        "tags": [
            {"key": "market_thesis", "label": "Market / Thesis", "locked": False, "at_entry": True},
            {"key": "pnl", "label": "P&L", "locked": False, "at_entry": True},
            {"key": "both", "label": "Both", "locked": False, "at_entry": True},
        ],
    },
    {
        "id": "management_issue", "label": "What changed?",
        "multi": False, "fixed_set": False, "entry_flag": False,
        "tags": [
            {"key": "none", "label": "None", "locked": True, "at_entry": True},
            {"key": "early_exit", "label": "Early exit", "locked": False, "at_entry": True},
            {"key": "late_exit", "label": "Late exit", "locked": False, "at_entry": True},
            {"key": "stop_change", "label": "Stop change", "locked": False, "at_entry": True},
            {"key": "overmanaged", "label": "Overmanaged", "locked": False, "at_entry": True},
            {"key": "under_managed", "label": "Under managed", "locked": False, "at_entry": True},
            {"key": "premature_scale_out", "label": "Premature scale out", "locked": False, "at_entry": True},
        ],
    },
    {
        "id": "emotion", "label": "What were you feeling?",
        "multi": True, "fixed_set": False, "entry_flag": True,
        "tags": [
            {"key": "calm", "label": "Calm", "locked": False, "at_entry": True},
            # Both fear states need an open position, so offering them before
            # entry invites a nonsense answer.
            {"key": "fear_of_loss", "label": "Fear of loss", "locked": False, "at_entry": False},
            {"key": "fear_of_giving_back", "label": "Fear of giving back", "locked": False, "at_entry": False},
            {"key": "greed", "label": "Greed", "locked": False, "at_entry": True},
            {"key": "frustration", "label": "Frustration", "locked": False, "at_entry": True},
            {"key": "impatience", "label": "Impatience", "locked": False, "at_entry": True},
            {"key": "overconfidence", "label": "Overconfidence", "locked": False, "at_entry": True},
            {"key": "distracted", "label": "Distracted", "locked": False, "at_entry": True},
        ],
    },
    {
        "id": "process_violation", "label": "Process violation",
        "multi": True, "fixed_set": False, "entry_flag": False,
        "tags": [
            {"key": "none", "label": "None", "locked": True, "at_entry": True},
            {"key": "traded_outside_plan", "label": "Traded outside plan", "locked": False, "at_entry": True},
            {"key": "exceeded_risk", "label": "Exceeded risk", "locked": False, "at_entry": True},
            {"key": "revenge_trade", "label": "Revenge trade", "locked": False, "at_entry": True},
            {"key": "overtraded", "label": "Overtraded", "locked": False, "at_entry": True},
        ],
    },
]

REVIEW_MARKER_IDS = tuple(g["id"] for g in REVIEW_MARKER_GROUPS)
```

- [ ] **Step 4: Add the migration**

In `database.py`, inside `init_db()`, beside the other `PRAGMA table_info` guards:

```python
        # Migration: review markers are key-addressed. `tag` stays the display
        # label; `tag_key` is the stable identity that trades store and code
        # branches on. Legacy tag groups leave tag_key NULL and keep using the
        # label as identity.
        tc_cols = [r[1] for r in conn.execute("PRAGMA table_info(tag_config)").fetchall()]
        if "tag_key" not in tc_cols:
            conn.execute("ALTER TABLE tag_config ADD COLUMN tag_key TEXT")
        if "locked" not in tc_cols:
            conn.execute("ALTER TABLE tag_config ADD COLUMN locked INTEGER NOT NULL DEFAULT 0")
        if "at_entry" not in tc_cols:
            conn.execute("ALTER TABLE tag_config ADD COLUMN at_entry INTEGER NOT NULL DEFAULT 1")
```

- [ ] **Step 5: Add the accessors**

In `database.py`, near `get_tag_config` (around line 1519):

```python
# ── Review markers ───────────────────────────────────────────────────────────
# These share tag_config with the legacy label-addressed groups but are a
# separate world: identity is `tag_key`, never the label. They must never be
# routed through save_tag_config or _cascade_tag_rename — that path treats the
# label as identity and cascades renames across trades, which is exactly what
# keys exist to avoid.

def get_review_marker_config():
    """{group_id: [{"key","label","locked","at_entry"}, ...]} or None."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT group_id, tag, tag_key, locked, at_entry FROM tag_config "
            "WHERE enabled = 1 AND tag_key IS NOT NULL ORDER BY group_id, position"
        ).fetchall()
        if not rows:
            return None
        result = {}
        for r in rows:
            result.setdefault(r["group_id"], []).append({
                "key": r["tag_key"], "label": r["tag"],
                "locked": bool(r["locked"]), "at_entry": bool(r["at_entry"]),
            })
        return result


def save_review_marker_group(group_id, tags):
    """Replace one group's tags with the provided ordered list.

    `tags` is [{"key","label","at_entry"}, ...]. No rename cascade runs: trades
    store keys, so a changed label reaches every existing trade for free.
    `locked` is not accepted from the caller — it is a property of the default
    vocabulary, reapplied here from REVIEW_MARKER_GROUPS.
    """
    import app_logic
    locked_keys = set()
    for g in app_logic.REVIEW_MARKER_GROUPS:
        if g["id"] == group_id:
            locked_keys = {t["key"] for t in g["tags"] if t["locked"]}
    with get_conn() as conn:
        conn.execute("DELETE FROM tag_config WHERE group_id = ? AND tag_key IS NOT NULL",
                     (group_id,))
        for position, t in enumerate(tags):
            conn.execute(
                "INSERT INTO tag_config (group_id, tag, tag_key, position, enabled, locked, at_entry) "
                "VALUES (?, ?, ?, ?, 1, ?, ?)",
                (group_id, t["label"], t["key"], position,
                 1 if t["key"] in locked_keys else 0,
                 1 if t.get("at_entry", True) else 0))


def get_group_multi(group_id, default):
    """Whether a tag group is multi-select. Falls back to `default` when unset."""
    raw = get_config("tag_multi:" + group_id, "")
    if raw == "":
        return bool(default)
    return raw == "1"


def set_group_multi(group_id, value):
    set_config("tag_multi:" + group_id, "1" if value else "0")
```

**`get_tag_config` must exclude the new rows.** Change its query to add `AND tag_key IS NULL`, or the legacy Technicals/Volume/Setup/Pre-trade cards would start rendering review markers. `test_review_marker_rows_never_collide_with_legacy_tag_groups` covers this.

- [ ] **Step 6: Run the tests and watch them pass**

Run: `python3 -m pytest tests/test_review_markers.py -q`
Expected: 10 passed.

- [ ] **Step 7: Mutation-check three tests**

Make each change, run, confirm the named test fails, restore. Report the observed outcome for each.

1. Drop `AND tag_key IS NULL` from `get_tag_config` → `test_review_marker_rows_never_collide_with_legacy_tag_groups` must fail.
2. Remove the `DELETE` from `save_review_marker_group` → `test_saving_a_group_replaces_rather_than_appends` must fail.
3. Change `ORDER BY group_id, position` to `ORDER BY group_id, tag` in `get_review_marker_config` → `test_saved_order_is_preserved` must fail.
4. Add a rename cascade to `save_review_marker_group` — e.g. `UPDATE trades SET emotion = ? WHERE emotion = ?` for a dropped key → `test_deleting_a_tag_does_not_touch_trades_that_used_it` must fail. This is the 4.8.1 shape; the test exists to make sure nobody reintroduces it here.

- [ ] **Step 8: Update SCHEMA.md**

Find the `tag_config` section (`grep -n "TAG_CONFIG" SCHEMA.md`) and add the three columns to its table, then append below it:

```markdown
`tag_key` is NULL for the legacy label-addressed groups (Technicals, Volume, Setup, Pre-trade),
whose identity is the label itself and whose renames cascade across trades. It is non-NULL for the
five review-marker groups (`management`, `management_driver`, `management_issue`, `emotion`,
`process_violation`), whose identity is the key — trades store the key, so a label may be renamed
freely with no cascade. `locked` blocks deletion of a tag; `at_entry` controls whether an emotion is
offered on the pre-entry question. Per-group multi-select lives in `app_config` under
`tag_multi:<group_id>`.
```

- [ ] **Step 9: Run the whole suite and commit**

```bash
python3 -m pytest tests/ -q
git add database.py app_logic.py SCHEMA.md tests/test_review_markers.py
git commit -m "feat: key-addressed review marker config"
```

---

### Task 2: Migrate `emotion` and `process_violation` to JSON arrays

**Files:**
- Modify: `database.py` (one-shot migration in `init_db()` behind an `app_config` flag; helpers near the assessment functions)
- Test: `tests/test_review_markers.py` (append)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `db.decode_marker_list(raw)` → `list` of keys; `[]` for NULL, `''`, or unparseable input
  - `db.encode_marker_list(values)` → JSON string, or `None` for an empty list

**Columns affected:** `trades.emotion`, `trades.process_violation`, `live_trades.emotion`, `live_trades.process_violation`. All four are TEXT and stay TEXT — only the content shape changes. `emotion_entry` is NOT migrated; it stays a single key.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_review_markers.py`:

```python
# ── Multi-value storage ───────────────────────────────────────────────────────

def test_decode_handles_arrays_scalars_and_blanks():
    """Scalars must decode too: the migration runs once, but a row written by an
    older build sitting in a backup, or restored later, would otherwise crash
    the review page rather than degrade."""
    assert db.decode_marker_list('["greed","impatience"]') == ["greed", "impatience"]
    assert db.decode_marker_list("greed") == ["greed"]
    assert db.decode_marker_list("") == []
    assert db.decode_marker_list(None) == []
    assert db.decode_marker_list("not json {") == ["not json {"]


def test_encode_round_trips_and_blanks_to_none():
    assert db.decode_marker_list(db.encode_marker_list(["greed"])) == ["greed"]
    assert db.encode_marker_list([]) is None


def test_migration_wraps_existing_scalars(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, 50.0, "10:00", "10:30")
    with db.get_conn() as conn:
        conn.execute("UPDATE trades SET emotion = 'greed', process_violation = 'overtraded' "
                     "WHERE id = ?", (trade_id,))
        conn.execute("DELETE FROM app_config WHERE key = 'migration_markers_to_lists'")

    db.init_db()

    with db.get_conn() as conn:
        row = conn.execute("SELECT emotion, process_violation FROM trades WHERE id = ?",
                           (trade_id,)).fetchone()
    assert row["emotion"] == '["greed"]'
    assert row["process_violation"] == '["overtraded"]'


def test_migration_is_idempotent_and_leaves_arrays_alone(tmp_db, day_id):
    """init_db runs on every request. A second pass must not wrap an array
    inside another array — the failure would be silent and unrecoverable."""
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, 50.0, "10:00", "10:30")
    with db.get_conn() as conn:
        conn.execute("UPDATE trades SET emotion = 'greed' WHERE id = ?", (trade_id,))
        conn.execute("DELETE FROM app_config WHERE key = 'migration_markers_to_lists'")

    db.init_db()
    with db.get_conn() as conn:
        conn.execute("DELETE FROM app_config WHERE key = 'migration_markers_to_lists'")
    db.init_db()

    with db.get_conn() as conn:
        row = conn.execute("SELECT emotion FROM trades WHERE id = ?", (trade_id,)).fetchone()
    assert row["emotion"] == '["greed"]'


def test_migration_leaves_blanks_and_nulls_alone(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, 50.0, "10:00", "10:30")
    with db.get_conn() as conn:
        conn.execute("UPDATE trades SET emotion = '', process_violation = NULL WHERE id = ?",
                     (trade_id,))
        conn.execute("DELETE FROM app_config WHERE key = 'migration_markers_to_lists'")

    db.init_db()

    with db.get_conn() as conn:
        row = conn.execute("SELECT emotion, process_violation FROM trades WHERE id = ?",
                           (trade_id,)).fetchone()
    assert row["emotion"] == ''
    assert row["process_violation"] is None
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m pytest tests/test_review_markers.py -q`
Expected: the five new tests FAIL — `AttributeError` on `db.decode_marker_list`, and the stored value is still `'greed'`.

Check the flag-key column name first: `grep -n "CREATE TABLE IF NOT EXISTS app_config" -A 5 database.py`. If `app_config`'s columns are not `key`/`value`, adapt the three `DELETE FROM app_config` lines in the tests to match — and only those.

- [ ] **Step 3: Add the codec helpers**

In `database.py`:

```python
# ── Multi-value review markers ───────────────────────────────────────────────
# emotion and process_violation hold a JSON array of keys. The column stays
# TEXT; only the shape of its content changed.

def decode_marker_list(raw):
    """Keys stored in a marker column, as a list.

    Tolerates a bare scalar. The migration converts every row once, but a
    database restored from an older backup would otherwise break the review
    page instead of simply reading as a single-item list.
    """
    import json
    if raw is None or raw == "":
        return []
    text = str(raw).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except ValueError:
            return [text]
        if isinstance(parsed, list):
            return [str(v) for v in parsed if v not in (None, "")]
        return [str(parsed)]
    return [text]


def encode_marker_list(values):
    """JSON array for storage, or None when nothing is selected."""
    import json
    cleaned = [str(v) for v in (values or []) if v not in (None, "")]
    if not cleaned:
        return None
    return json.dumps(cleaned)
```

- [ ] **Step 4: Add the one-shot migration**

In `database.py`, inside `init_db()`, after the `tag_config` column guards from Task 1:

```python
        # One-shot: emotion and process_violation became multi-select, so their
        # scalar values are wrapped into single-item JSON arrays. Guarded by a
        # flag because init_db runs on every request; rows already holding an
        # array are skipped by the `NOT LIKE '[%'` filter, so a lost flag
        # cannot double-wrap.
        if not conn.execute(
            "SELECT 1 FROM app_config WHERE key = 'migration_markers_to_lists'"
        ).fetchone():
            for table in ("trades", "live_trades"):
                for column in ("emotion", "process_violation"):
                    conn.execute(f"""
                        UPDATE {table}
                           SET {column} = '["' || {column} || '"]'
                         WHERE {column} IS NOT NULL
                           AND {column} <> ''
                           AND {column} NOT LIKE '[%'
                    """)
            conn.execute(
                "INSERT OR REPLACE INTO app_config (key, value) "
                "VALUES ('migration_markers_to_lists', '1')")
```

The `NOT LIKE '[%'` filter is the real protection — the flag only saves the work. Both together mean a wiped flag cannot corrupt data.

- [ ] **Step 5: Run the tests and watch them pass**

Run: `python3 -m pytest tests/test_review_markers.py -q`
Expected: 15 passed.

- [ ] **Step 6: Mutation-check two tests**

1. Remove `AND {column} NOT LIKE '[%'` from the UPDATE → `test_migration_is_idempotent_and_leaves_arrays_alone` must fail with a double-wrapped value.
2. Change `decode_marker_list` to return `[]` for a bare scalar → `test_decode_handles_arrays_scalars_and_blanks` must fail.

Report the observed outcome for each.

- [ ] **Step 7: Verify against a COPY of the real journal**

```bash
SC="$(dirname "$(mktemp -u)")"; cp data/journal.db "$SC/rm.db"
python3 - <<PY
import sqlite3, database as db
con = sqlite3.connect("$SC/rm.db")
before = con.execute("SELECT COUNT(*) FROM trades WHERE emotion IS NOT NULL AND emotion <> ''").fetchone()[0]
con.close()
db.DB_PATH = "$SC/rm.db"; db.init_db(); db.init_db()
con = sqlite3.connect("$SC/rm.db")
rows = con.execute("SELECT emotion, process_violation FROM trades WHERE emotion IS NOT NULL AND emotion <> ''").fetchall()
after = len(rows)
print("emotion rows before:", before, "after:", after)
print("sample:", rows[:4])
assert before == after, "rows lost"
assert all(r[0].startswith("[") and not r[0].startswith('["[') for r in rows), "bad wrap"
print("OK")
PY
```

Expected: the row count is unchanged and every value reads like `["greed"]`, never `["[\"greed\"]"]`. Never point `DB_PATH` at `data/journal.db` itself.

- [ ] **Step 8: Run the whole suite and commit**

```bash
python3 -m pytest tests/ -q
git add database.py tests/test_review_markers.py
git commit -m "feat: store emotion and process violation as key lists"
```

---

### Task 3: Runtime vocabulary, validation, and the readers

**Files:**
- Modify: `app_logic.py` (`_ASSESSMENT_VOCAB` around line 678, `validate_assessment` around line 691, `build_grade_analytics` around line 1028)
- Modify: `templates/weekly_review.html` (around line 473, the `top_emotion` label)
- Test: `tests/test_review_markers.py` (append)

**Interfaces:**
- Consumes: `logic.REVIEW_MARKER_GROUPS`, `db.get_review_marker_config()`, `db.get_group_multi()`, `db.decode_marker_list()`, `db.encode_marker_list()`.
- Produces:
  - `logic.get_review_markers()` → ordered list of group dicts, defaults overlaid with saved config
  - `logic.marker_keys(group_id)` → tuple of keys, in order
  - `logic.marker_label(group_id, key)` → label, falling back to the key when unknown
  - `logic.entry_emotion_keys()` → tuple of emotion keys with `at_entry`
  - `logic.MULTI_MARKER_FIELDS` = `("emotion", "process_violation")`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_review_markers.py`:

```python
# ── Runtime vocabulary ────────────────────────────────────────────────────────

def test_configured_labels_override_defaults_without_touching_keys(tmp_db):
    """The whole point of keys: a rename changes what you read, never what is
    stored or branched on."""
    db.save_review_marker_group("process_violation", [
        {"key": "none", "label": "Clean", "at_entry": True},
        {"key": "overtraded", "label": "Traded too much", "at_entry": True},
    ])

    assert logic.marker_label("process_violation", "none") == "Clean"
    assert logic.marker_keys("process_violation") == ("none", "overtraded")


def test_unconfigured_groups_fall_back_to_defaults(tmp_db):
    assert logic.marker_label("emotion", "fear_of_loss") == "Fear of loss"
    assert "calm" in logic.marker_keys("emotion")


def test_marker_label_falls_back_to_the_key_for_a_retired_tag(tmp_db):
    """A trade tagged with an emotion later deleted from the vocabulary must
    still render something rather than raising on the review page."""
    assert logic.marker_label("emotion", "wistful") == "wistful"


def test_entry_emotions_follow_the_at_entry_flag(tmp_db):
    assert "fear_of_loss" not in logic.entry_emotion_keys()
    assert "calm" in logic.entry_emotion_keys()

    db.save_review_marker_group("emotion", [
        {"key": "calm", "label": "Calm", "at_entry": False},
        {"key": "fear_of_loss", "label": "Fear of loss", "at_entry": True},
    ])

    assert logic.entry_emotion_keys() == ("fear_of_loss",)


# ── Validation ────────────────────────────────────────────────────────────────

def test_multi_fields_accept_and_clean_a_list(tmp_db):
    cleaned, err = logic.validate_assessment(
        {"grade": "C", "emotion": ["greed", "impatience"]})

    assert err is None
    assert cleaned["emotion"] == ["greed", "impatience"]


def test_multi_fields_still_accept_a_bare_scalar(tmp_db):
    """The live_v2 review chain sends one value per click today; it must keep
    working while the UI catches up in Task 6."""
    cleaned, err = logic.validate_assessment({"grade": "C", "emotion": "greed"})

    assert err is None
    assert cleaned["emotion"] == ["greed"]


def test_an_unknown_key_is_still_rejected(tmp_db):
    """The vocabulary moved to config; it did not stop being closed."""
    cleaned, err = logic.validate_assessment({"grade": "C", "emotion": ["elated"]})

    assert cleaned == {}
    assert "emotion" in err


def test_none_wins_over_everything_else_in_a_multi_field(tmp_db):
    cleaned, err = logic.validate_assessment(
        {"grade": "C", "process_violation": ["none", "overtraded"]})

    assert err is None
    assert cleaned["process_violation"] == ["none"]


def test_any_real_violation_still_conflicts_with_an_a_grade(tmp_db):
    cleaned, err = logic.validate_assessment(
        {"grade": "A", "process_violation": ["none", "revenge_trade"]})

    assert cleaned == {}
    assert "A grade" in err


def test_the_a_grade_rule_survives_relabelling_none(tmp_db):
    """It keys off `none`, not the word 'None'."""
    db.save_review_marker_group("process_violation", [
        {"key": "none", "label": "Clean", "at_entry": True},
        {"key": "overtraded", "label": "Overtraded", "at_entry": True},
    ])

    _, ok_err = logic.validate_assessment({"grade": "A", "process_violation": ["none"]})
    _, bad_err = logic.validate_assessment({"grade": "A", "process_violation": ["overtraded"]})

    assert ok_err is None
    assert bad_err is not None


# ── Readers ───────────────────────────────────────────────────────────────────

def test_analytics_count_every_emotion_in_a_list(tmp_db, day_id):
    """Counting the raw column would score '["greed","impatience"]' as one
    exotic emotion and report it as the top one."""
    for n, emotions in enumerate([["greed", "impatience"], ["greed"]], start=1):
        tid = db.insert_trade(day_id, n, "Long", 1, 7700.0, 7710.0, -50.0, "10:00", "10:30")
        db.set_trade_assessment(tid, grade="C", emotion=db.encode_marker_list(emotions))

    stats = logic.build_grade_analytics(None, "2026-09-01", "2026-09-30")

    assert stats["bc_diagnosis"]["top_emotion"][0] == "greed"
    assert stats["bc_diagnosis"]["top_emotion"][1] == 2
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m pytest tests/test_review_markers.py -q`
Expected: the eleven new tests FAIL — `AttributeError` on the four new `logic.` functions, and list payloads rejected by the old scalar `value not in vocab` check.

`build_grade_analytics`'s exact signature may differ: run `grep -n "def build_grade_analytics" app_logic.py` and adapt only the call in the last test.

- [ ] **Step 3: Add the runtime accessors**

In `app_logic.py`, after `REVIEW_MARKER_GROUPS`:

```python
MULTI_MARKER_FIELDS = ("emotion", "process_violation")
# Both multi groups carry a `none` key meaning "nothing to record". Choosing it
# alongside a real value is not a state worth storing, so `none` wins.
MARKER_NONE_KEY = "none"


def get_review_markers():
    """The five groups, defaults overlaid with any saved config."""
    saved = db.get_review_marker_config() or {}
    groups = []
    for g in REVIEW_MARKER_GROUPS:
        merged = dict(g)
        if g["id"] in saved:
            merged["tags"] = saved[g["id"]]
        merged["multi"] = db.get_group_multi(g["id"], g["multi"])
        groups.append(merged)
    return groups


def _marker_group(group_id):
    for g in get_review_markers():
        if g["id"] == group_id:
            return g
    return None


def marker_keys(group_id):
    g = _marker_group(group_id)
    return tuple(t["key"] for t in g["tags"]) if g else ()


def marker_label(group_id, key):
    """Display label for a key, falling back to the key itself.

    A trade may carry a key later deleted from the vocabulary; the review page
    must render it rather than raise.
    """
    g = _marker_group(group_id)
    if g:
        for t in g["tags"]:
            if t["key"] == key:
                return t["label"]
    return key


def entry_emotion_keys():
    """Emotions offered before entry — those flagged `at_entry`."""
    g = _marker_group("emotion")
    return tuple(t["key"] for t in g["tags"] if t.get("at_entry", True)) if g else ()
```

- [ ] **Step 4: Make validation runtime and list-aware**

Replace the module-level `_ASSESSMENT_VOCAB` dict with a function, and update the loop in `validate_assessment`:

```python
def assessment_vocab():
    """Valid values per assessment field, read at request time.

    Was a module constant. The five review vocabularies are now editable, so
    closing over them at import would validate against a stale list until the
    process restarted.
    """
    vocab = {"grade": GRADES}
    for group_id in REVIEW_MARKER_IDS:
        vocab[group_id] = marker_keys(group_id)
    vocab["emotion_entry"] = entry_emotion_keys()
    return vocab
```

In `validate_assessment`, replace the `for key, vocab in _ASSESSMENT_VOCAB.items():` loop with:

```python
    cleaned = {}
    for key, vocab in assessment_vocab().items():
        if key not in fields:
            continue
        value = fields[key]
        if value in (None, "", []):
            cleaned[key] = [] if key in MULTI_MARKER_FIELDS else None
            continue
        if key in MULTI_MARKER_FIELDS:
            # A bare scalar is accepted so a caller that has not moved to lists
            # yet keeps working.
            values = list(value) if isinstance(value, (list, tuple)) else [value]
            for v in values:
                if v not in vocab:
                    return {}, f"{key} must be one of {', '.join(vocab)}"
            if MARKER_NONE_KEY in values and len(values) > 1:
                values = [MARKER_NONE_KEY]
            cleaned[key] = values
            continue
        if value not in vocab:
            return {}, f"{key} must be one of {', '.join(vocab)}"
        cleaned[key] = value
```

Then update the A-grade rule to read the list:

```python
    # The violation field is only asked on a B or C grade. A grade change that
    # would leave a stored violation stranded on an A grade is rejected rather
    # than silently cleared — that would discard something the trader
    # deliberately recorded. Keyed off MARKER_NONE_KEY, so relabelling "None"
    # cannot break it.
    violations = merged.get("process_violation") or []
    if isinstance(violations, str):
        violations = db.decode_marker_list(violations)
    if any(v != MARKER_NONE_KEY for v in violations) and merged.get("grade") == "A":
        return {}, "process_violation cannot be set on an A grade — clear it in the same request"
```

**`set_trade_assessment` takes strings.** Whoever calls it with a cleaned multi field must encode first — `db.encode_marker_list(cleaned["emotion"])`. Task 4 does that in the route.

- [ ] **Step 5: Update the analytics reader**

In `build_grade_analytics`, replace the scalar emotion count:

```python
            # emotion holds a list of keys now; every one counts toward its own
            # tally. Counting the raw column would score a two-emotion trade as
            # one exotic value and report it as the most common.
            for e in db.decode_marker_list(r["emotion"]):
                bc_emotions[e] = bc_emotions.get(e, 0) + 1
```

- [ ] **Step 6: Update the weekly template's label**

In `templates/weekly_review.html` around line 473, replace `top_emotion[0].replace('_', ' ')` with the configured label. Add to the payload in `build_weekly_review_data` (or wherever `bc_diagnosis` is assembled) a resolved label, or expose `marker_label` as a Jinja global next to `board_cell` in `server.py`:

```python
app.jinja_env.globals["marker_label"] = logic.marker_label
```

and render `{{ marker_label('emotion', s.bc_diagnosis.top_emotion[0]) }}`.

- [ ] **Step 7: Run the tests and watch them pass**

Run: `python3 -m pytest tests/test_review_markers.py -q`
Expected: 26 passed.

- [ ] **Step 8: Mutation-check four tests**

1. Drop the `if MARKER_NONE_KEY in values and len(values) > 1` normalisation → `test_none_wins_over_everything_else_in_a_multi_field` must fail.
2. Change the A-grade check to compare against the literal string `"None"` → `test_the_a_grade_rule_survives_relabelling_none` must fail.
3. Revert the analytics count to `bc_emotions[r["emotion"]] = …` → `test_analytics_count_every_emotion_in_a_list` must fail.
4. Make `marker_label` raise instead of falling back to the key → `test_marker_label_falls_back_to_the_key_for_a_retired_tag` must fail.

Report the observed outcome for each.

- [ ] **Step 9: Run the whole suite and commit**

```bash
python3 -m pytest tests/ -q
git add app_logic.py templates/weekly_review.html server.py tests/test_review_markers.py
git commit -m "feat: validate review markers against the configured vocabulary"
```

---

### Task 4: API routes

**Files:**
- Modify: `server.py` (new routes beside `api_save_tag_config`, around line 731; the assessment routes around line 1015; `api_save_tag_config` itself gains a guard)
- Test: `tests/test_review_markers.py` (append)

**Interfaces:**
- Consumes: `logic.get_review_markers()`, `logic.REVIEW_MARKER_GROUPS`, `logic.validate_assessment`, `db.save_review_marker_group`, `db.set_group_multi`, `db.encode_marker_list`.
- Produces:
  - `GET  /api/settings/review-markers` → `{"groups": [...]}`
  - `POST /api/settings/review-markers/<group_id>` accepting `{"tags": [{"key","label","at_entry"}], "multi": bool}`
  - `POST /api/settings/review-markers/<group_id>/reset`
  - `POST /api/settings/tags/<group_id>` also accepts an optional `"multi"` bool, so the legacy toggle finally persists

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_review_markers.py`:

```python
# ── API ───────────────────────────────────────────────────────────────────────

def test_get_returns_every_group_with_flags(client, tmp_db):
    groups = {g["id"]: g for g in client.get("/api/settings/review-markers").get_json()["groups"]}

    assert set(groups) == {"management", "management_driver", "management_issue",
                           "emotion", "process_violation"}
    assert groups["emotion"]["multi"] is True
    assert groups["management"]["fixed_set"] is True
    assert groups["management"]["tags"][0]["locked"] is True


def test_post_saves_labels_order_and_the_multi_flag(client, tmp_db):
    res = client.post("/api/settings/review-markers/process_violation", json={
        "tags": [{"key": "none", "label": "Clean", "at_entry": True},
                 {"key": "overtraded", "label": "Overtraded", "at_entry": True}],
        "multi": False})

    assert res.status_code == 200
    assert logic.marker_label("process_violation", "none") == "Clean"
    assert db.get_group_multi("process_violation", True) is False


def test_post_refuses_to_delete_a_locked_tag(client, tmp_db):
    """`none` is what the A-grade rule keys off. Losing it would make every
    A-grade save fail with a message about a value the trader cannot see."""
    res = client.post("/api/settings/review-markers/process_violation", json={
        "tags": [{"key": "overtraded", "label": "Overtraded", "at_entry": True}]})

    assert res.status_code == 400
    assert "none" in res.get_json()["error"]
    assert "none" in logic.marker_keys("process_violation")


def test_post_allows_renaming_a_locked_tag(client, tmp_db):
    """Locked blocks deletion, not renaming — only the key is load-bearing."""
    res = client.post("/api/settings/review-markers/process_violation", json={
        "tags": [{"key": "none", "label": "Clean", "at_entry": True},
                 {"key": "overtraded", "label": "Overtraded", "at_entry": True}]})

    assert res.status_code == 200
    assert logic.marker_label("process_violation", "none") == "Clean"


def test_post_refuses_a_new_tag_on_a_fixed_set_group(client, tmp_db):
    """Nothing branches on a third management state, so it could never be read."""
    res = client.post("/api/settings/review-markers/management", json={
        "tags": [{"key": "followed", "label": "Followed process", "at_entry": True},
                 {"key": "deviated", "label": "Deviated", "at_entry": True},
                 {"key": "partly", "label": "Partly", "at_entry": True}]})

    assert res.status_code == 400
    assert logic.marker_keys("management") == ("followed", "deviated")


def test_post_rejects_an_unknown_group(client, tmp_db):
    res = client.post("/api/settings/review-markers/not_a_group", json={"tags": []})

    assert res.status_code == 400


def test_reset_restores_the_defaults(client, tmp_db):
    client.post("/api/settings/review-markers/process_violation", json={
        "tags": [{"key": "none", "label": "Clean", "at_entry": True}]})

    client.post("/api/settings/review-markers/process_violation/reset")

    assert logic.marker_label("process_violation", "none") == "None"
    assert len(logic.marker_keys("process_violation")) == 5


def test_legacy_tag_route_now_persists_its_multi_flag(client, tmp_db):
    """The Settings toggle has never saved anything: saveGroup posted {tags}
    only and the card re-rendered from a constant. Fixed here for the existing
    groups too, or the two new multi sections would be equally decorative."""
    client.post("/api/settings/tags/volume", json={"tags": ["Avg"], "multi": True})

    assert db.get_group_multi("volume", False) is True


def test_assessment_route_stores_a_multi_field_as_a_list(client, tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, -50.0, "10:00", "10:30")

    res = client.post(f"/api/trade/{trade_id}/assessment",
                      json={"grade": "C", "emotion": ["greed", "impatience"]})

    assert res.status_code == 200
    with db.get_conn() as conn:
        stored = conn.execute("SELECT emotion FROM trades WHERE id = ?", (trade_id,)).fetchone()[0]
    assert db.decode_marker_list(stored) == ["greed", "impatience"]
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m pytest tests/test_review_markers.py -q`
Expected: the nine new tests FAIL — 404 on the new routes, and the assessment route storing a stringified list.

Confirm the assessment route's path first: `grep -n "assessment" server.py | head`. Use whatever it actually is in the last test.

- [ ] **Step 3: Add the review-marker routes**

In `server.py`, beside `api_save_tag_config`:

```python
@app.route("/api/settings/review-markers", methods=["GET"])
def api_get_review_markers():
    return jsonify({"groups": logic.get_review_markers()})


@app.route("/api/settings/review-markers/<group_id>", methods=["POST"])
def api_save_review_markers(group_id):
    defaults = {g["id"]: g for g in logic.REVIEW_MARKER_GROUPS}
    if group_id not in defaults:
        return jsonify({"error": "unknown group"}), 400
    body = request.get_json(silent=True) or {}
    tags = body.get("tags", [])
    if not isinstance(tags, list):
        return jsonify({"error": "tags must be a list"}), 400

    cleaned = []
    for t in tags:
        key = str(t.get("key", "")).strip()
        label = str(t.get("label", "")).strip()
        if not key or not label:
            return jsonify({"error": "every tag needs a key and a label"}), 400
        cleaned.append({"key": key, "label": label,
                        "at_entry": bool(t.get("at_entry", True))})

    default = defaults[group_id]
    default_keys = {t["key"] for t in default["tags"]}
    sent_keys = {t["key"] for t in cleaned}

    missing = [t["key"] for t in default["tags"] if t["locked"] and t["key"] not in sent_keys]
    if missing:
        return jsonify({"error": "cannot delete locked tag(s): " + ", ".join(missing)}), 400

    if default["fixed_set"] and sent_keys != default_keys:
        return jsonify({"error": "this group's options are fixed; labels may be edited"}), 400

    db.save_review_marker_group(group_id, cleaned)
    if "multi" in body and not default["fixed_set"]:
        db.set_group_multi(group_id, bool(body["multi"]))
    return jsonify({"ok": True, "group_id": group_id})


@app.route("/api/settings/review-markers/<group_id>/reset", methods=["POST"])
def api_reset_review_markers(group_id):
    defaults = {g["id"]: g for g in logic.REVIEW_MARKER_GROUPS}
    if group_id not in defaults:
        return jsonify({"error": "unknown group"}), 400
    db.save_review_marker_group(group_id, [
        {"key": t["key"], "label": t["label"], "at_entry": t["at_entry"]}
        for t in defaults[group_id]["tags"]])
    db.set_group_multi(group_id, defaults[group_id]["multi"])
    return jsonify({"ok": True, "group_id": group_id})
```

- [ ] **Step 4: Make the legacy tag route persist its multi flag**

In `api_save_tag_config`, before the return:

```python
    if "multi" in body:
        db.set_group_multi(group_id, bool(body["multi"]))
```

- [ ] **Step 5: Encode multi fields in the assessment routes**

Wherever a validated assessment reaches `db.set_trade_assessment` / `db.set_live_trade_assessment`, encode the list fields first — the DB layer stores strings:

```python
    for field in logic.MULTI_MARKER_FIELDS:
        if field in cleaned:
            cleaned[field] = db.encode_marker_list(cleaned[field])
```

Apply it in both the trade and the live-trade assessment routes. Also update the entry-emotion check around line 1015 to read the configured set:

```python
    if entry_emotion and entry_emotion not in logic.entry_emotion_keys():
        return jsonify({"error": "emotion_entry must be one of "
                                 + ", ".join(logic.entry_emotion_keys())}), 400
```

- [ ] **Step 6: Run the tests and watch them pass**

Run: `python3 -m pytest tests/test_review_markers.py -q`
Expected: 35 passed.

- [ ] **Step 7: Mutation-check three tests**

1. Delete the `missing` locked-tag check → `test_post_refuses_to_delete_a_locked_tag` must fail.
2. Delete the `fixed_set` check → `test_post_refuses_a_new_tag_on_a_fixed_set_group` must fail.
3. Remove the encode loop from Step 5 → `test_assessment_route_stores_a_multi_field_as_a_list` must fail.

Report the observed outcome for each.

- [ ] **Step 8: Run the whole suite and commit**

```bash
python3 -m pytest tests/ -q
git add server.py tests/test_review_markers.py
git commit -m "feat: review marker settings API"
```

---

### Task 5: The Review Markers settings tab

**Files:**
- Modify: `templates/settings.html` (sub-tab buttons around line 378; a new sub-tab content block after `subtab-trade-tags`; JS near `saveGroup`, around line 1164)
- Modify: `server.py` (pass the groups to the settings template)
- Test: `tests/test_review_markers.py` (append)

**Interfaces:**
- Consumes: `GET/POST /api/settings/review-markers`, and `logic.get_review_markers()` for the initial render.
- Produces: markup carrying `class="rm-card"`, `data-group`, `data-key`, `data-locked`, and the `rm-entry` checkbox.

**Tab order:** Technical Markers, **Review Markers**, Observation Markers, Day Markers. Review Markers is second.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_review_markers.py`:

```python
# ── Settings UI ───────────────────────────────────────────────────────────────

def _settings_html(client):
    return client.get("/settings").get_data(as_text=True)


def _rm_card(html, group_id):
    """The single review-marker card block for one group, div-balanced.

    Needed because every card carries the same classes — a bare substring check
    for a lock icon or an entry checkbox can pass against a neighbouring card
    instead of the one under test.
    """
    marker = 'data-group="{}"'.format(group_id)
    idx = html.index('class="rm-card"')
    while marker not in html[idx:html.index(">", idx) + 1]:
        idx = html.index('class="rm-card"', idx + 1)
    start = html.rfind("<div", 0, idx)
    pos, depth = start, 0
    while True:
        nxt_open = html.find("<div", pos)
        nxt_close = html.find("</div>", pos)
        if nxt_close == -1:
            raise AssertionError("unclosed rm-card for " + group_id)
        if nxt_open != -1 and nxt_open < nxt_close:
            depth += 1
            pos = nxt_open + 4
        else:
            depth -= 1
            pos = nxt_close + 6
            if depth == 0:
                return html[start:pos]


def test_review_markers_is_the_second_sub_tab(client, tmp_db):
    html = _settings_html(client)
    order = [html.index(label) for label in
             ("Technical Markers", "Review Markers", "Observation Markers", "Day Markers")]

    assert order == sorted(order)


def test_all_five_cards_render(client, tmp_db):
    html = _settings_html(client)

    for group_id in ("management", "management_driver", "management_issue",
                     "emotion", "process_violation"):
        assert 'data-group="{}"'.format(group_id) in html


def test_a_locked_row_has_no_delete_control_but_keeps_its_text_input(client, tmp_db):
    """Locked blocks deletion only — the label must stay editable."""
    card = _rm_card(_settings_html(client), "process_violation")
    none_row = card[card.index('data-key="none"'):]
    none_row = none_row[:none_row.index("</div>")]

    assert 'data-locked="true"' in none_row
    assert "rm-del" not in none_row
    assert "<input" in none_row


def test_an_unlocked_row_keeps_its_delete_control(client, tmp_db):
    card = _rm_card(_settings_html(client), "process_violation")
    row = card[card.index('data-key="overtraded"'):]
    row = row[:row.index("</div>")]

    assert "rm-del" in row


def test_the_entry_checkbox_appears_only_on_the_emotion_card(client, tmp_db):
    html = _settings_html(client)

    assert "rm-entry" in _rm_card(html, "emotion")
    assert "rm-entry" not in _rm_card(html, "process_violation")


def test_a_fixed_set_card_offers_no_add_box(client, tmp_db):
    """Adding a third management state would produce a value nothing reads."""
    assert "rm-add" not in _rm_card(_settings_html(client), "management")
    assert "rm-add" in _rm_card(_settings_html(client), "emotion")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m pytest tests/test_review_markers.py -q`
Expected: FAIL with `ValueError: substring not found` — no `rm-card` markup exists.

Confirm the settings route's path and template variables first: `grep -n "def settings" -A 8 server.py`.

- [ ] **Step 3: Pass the groups to the template**

In `server.py`'s settings view, add `review_marker_groups=logic.get_review_markers()` to the `render_template` call. Do not remove or reorder the existing kwargs.

- [ ] **Step 4: Add the sub-tab button**

In `templates/settings.html` around line 378, insert between Technical Markers and Observation Markers:

```html
        <button class="sub-tab" onclick="showSubTab('review-markers', this)">Review Markers</button>
```

- [ ] **Step 5: Add the sub-tab content**

After the `subtab-trade-tags` block:

```html
      <!-- Review Markers sub-tab -->
      <div class="sub-tab-content" id="subtab-review-markers" style="display:none;">
        <div class="tag-config-grid">
          {% for g in review_marker_groups %}
          <div class="tag-config-card rm-card" data-group="{{ g.id }}"
               data-fixed="{{ 'true' if g.fixed_set else 'false' }}">
            <div class="tag-config-header">
              <div class="tag-config-title">{{ g.label }}
                <span class="tag-count">({{ g.tags|length }} tags)</span></div>
              {% if not g.fixed_set %}
              <div class="multi-toggle">
                <span>Multi-select</span>
                <div class="toggle-switch {{ 'on' if g.multi else '' }}" id="rm-multi-{{ g.id }}"
                     onclick="rmToggleMulti('{{ g.id }}', this)"></div>
              </div>
              {% endif %}
            </div>
            <div class="tag-config-body">
              <div id="rm-list-{{ g.id }}">
                {% for t in g.tags %}
                <div class="tag-item rm-row" data-key="{{ t.key }}"
                     data-locked="{{ 'true' if t.locked else 'false' }}">
                  <input class="tag-item-text rm-label" value="{{ t.label }}"
                         oninput="rmMarkDirty('{{ g.id }}')">
                  {% if g.entry_flag %}
                  <label class="rm-entry" title="Offer this before entry">
                    <input type="checkbox" {{ 'checked' if t.at_entry else '' }}
                           onchange="rmMarkDirty('{{ g.id }}')"> entry
                  </label>
                  {% endif %}
                  {% if t.locked %}
                  <span class="rm-lock" title="Required — the review logic reads this option. You can rename it.">🔒</span>
                  {% else %}
                  <span class="rm-del" onclick="rmDeleteRow(this, '{{ g.id }}')">✕</span>
                  {% endif %}
                </div>
                {% endfor %}
              </div>
              {% if not g.fixed_set %}
              <div class="rm-add-row">
                <input class="rm-add" id="rm-add-{{ g.id }}" placeholder="Add new tag…">
                <button onclick="rmAddRow('{{ g.id }}')">+ Add</button>
              </div>
              {% endif %}
            </div>
            <div class="tag-config-footer">
              <span class="save-status" id="rm-status-{{ g.id }}">—</span>
              <span onclick="rmReset('{{ g.id }}')">↺ Reset to defaults</span>
              <button onclick="rmSave('{{ g.id }}')">SAVE</button>
            </div>
          </div>
          {% endfor %}
        </div>
      </div>
```

- [ ] **Step 6: Add the JavaScript**

Near `saveGroup` in the page's existing `<script>`:

```javascript
  // ── Review markers ──────────────────────────────────────────────────────
  // Rows are key-addressed: the label is editable, the key never changes. A new
  // row's key is slugified from its label once, at creation.
  function rmMarkDirty(groupId) {
    const el = document.getElementById('rm-status-' + groupId);
    el.textContent = 'Unsaved'; el.className = 'save-status saving';
  }

  function rmToggleMulti(groupId, el) {
    el.classList.toggle('on');
    rmMarkDirty(groupId);
  }

  function rmSlug(label) {
    return label.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  }

  function rmAddRow(groupId) {
    const input = document.getElementById('rm-add-' + groupId);
    const label = input.value.trim();
    if (!label) return;
    const key = rmSlug(label);
    if (!key) return;
    const list = document.getElementById('rm-list-' + groupId);
    if (list.querySelector(`[data-key="${key}"]`)) return;   // already present
    const entry = document.querySelector(`.rm-card[data-group="${groupId}"] .rm-entry`)
      ? `<label class="rm-entry"><input type="checkbox" checked
           onchange="rmMarkDirty('${groupId}')"> entry</label>` : '';
    const row = document.createElement('div');
    row.className = 'tag-item rm-row';
    row.dataset.key = key;
    row.dataset.locked = 'false';
    row.innerHTML = `<input class="tag-item-text rm-label" value="${label}"
        oninput="rmMarkDirty('${groupId}')">${entry}
        <span class="rm-del" onclick="rmDeleteRow(this, '${groupId}')">✕</span>`;
    list.appendChild(row);
    input.value = '';
    rmMarkDirty(groupId);
  }

  function rmDeleteRow(el, groupId) {
    el.closest('.rm-row').remove();
    rmMarkDirty(groupId);
  }

  async function rmSave(groupId) {
    const card = document.querySelector(`.rm-card[data-group="${groupId}"]`);
    const tags = [...card.querySelectorAll('.rm-row')].map(row => {
      const box = row.querySelector('.rm-entry input');
      return { key: row.dataset.key,
               label: row.querySelector('.rm-label').value.trim(),
               at_entry: box ? box.checked : true };
    }).filter(t => t.label);
    const toggle = document.getElementById('rm-multi-' + groupId);
    const payload = { tags: tags };
    if (toggle) payload.multi = toggle.classList.contains('on');
    const status = document.getElementById('rm-status-' + groupId);
    status.textContent = 'Saving…'; status.className = 'save-status saving';
    try {
      const res = await fetch('/api/settings/review-markers/' + groupId, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload) });
      if (res.ok) {
        status.textContent = '✓ Saved'; status.className = 'save-status saved';
        setTimeout(() => { status.textContent = '—'; status.className = 'save-status'; }, 2500);
      } else {
        const err = await res.json();
        status.textContent = '✗ ' + (err.error || 'Error');
        status.className = 'save-status error';
      }
    } catch (e) {
      status.textContent = '✗ Network error'; status.className = 'save-status error';
    }
  }

  async function rmReset(groupId) {
    await fetch('/api/settings/review-markers/' + groupId + '/reset', { method: 'POST' });
    location.reload();
  }
```

- [ ] **Step 7: Make the legacy toggle send its flag**

In the existing `saveGroup`, include the toggle state so the four original groups persist it too:

```javascript
      const toggle = document.getElementById('multi-' + groupId);
      const body = { tags };
      if (toggle) body.multi = toggle.classList.contains('on');
```

and post `body` instead of `{ tags }`.

- [ ] **Step 8: Add the CSS**

In the page's existing `<style>` block, matching the surrounding dark palette:

```css
.rm-row { display:flex; align-items:center; gap:8px; }
.rm-entry { font-size:11px; color:var(--muted); display:flex; align-items:center; gap:4px; white-space:nowrap; }
.rm-lock { opacity:0.55; font-size:12px; cursor:help; }
.rm-del { cursor:pointer; opacity:0.6; padding:0 4px; }
.rm-del:hover { opacity:1; color:var(--red); }
.rm-add-row { display:flex; gap:8px; margin-top:8px; }
.rm-add { flex:1; }
```

Check the variable names exist first: `grep -n "^\s*--" templates/base.html | head -20`. Substitute the nearest defined one if `--red` or `--muted` is absent, and note the substitution in the report.

- [ ] **Step 9: Run the tests and watch them pass**

Run: `python3 -m pytest tests/test_review_markers.py -q`
Expected: 41 passed.

- [ ] **Step 10: Check the JavaScript parses**

```bash
python3 - <<'PY'
import re, subprocess, tempfile, os
s = open("templates/settings.html").read()
js = "\n".join(m for m in re.findall(r"<script[^>]*>(.*?)</script>", s, re.S) if "src=" not in m)
js = re.sub(r"\{\{.*?\}\}", "0", js); js = re.sub(r"\{%.*?%\}", "", js)
t = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False); t.write(js); t.close()
r = subprocess.run(["node", "--check", t.name], capture_output=True, text=True)
print("JS parse:", "OK" if r.returncode == 0 else "FAIL\n" + r.stderr[:600]); os.unlink(t.name)
PY
```

Expected: `JS parse: OK`.

- [ ] **Step 11: Mutation-check three tests**

1. Move the Review Markers button after Observation Markers → `test_review_markers_is_the_second_sub_tab` must fail.
2. Render `rm-del` unconditionally (drop the `{% if t.locked %}` branch) → `test_a_locked_row_has_no_delete_control_but_keeps_its_text_input` must fail.
3. Drop the `{% if g.entry_flag %}` guard so every card shows the checkbox → `test_the_entry_checkbox_appears_only_on_the_emotion_card` must fail.

Report the observed outcome for each.

- [ ] **Step 12: Run the whole suite and commit**

```bash
python3 -m pytest tests/ -q
git add templates/settings.html server.py tests/test_review_markers.py
git commit -m "feat: Review Markers settings tab"
```

---

### Task 6: The review chain reads config and goes multi-select

**Files:**
- Modify: `templates/live_v2.html` (`chipLabel` / `chipBtn` / `mgmtBtn`, around line 5214; `setReviewField`; the review payload)
- Modify: `server.py` (expose the groups to the live template)
- Modify: `VERSION`, `CHANGELOG.md`
- Test: `tests/test_review_markers.py` (append)

**Interfaces:**
- Consumes: `logic.get_review_markers()`, `logic.marker_label`, `POST /api/trade/<id>/assessment` with list values.
- Produces: the review chain rendering configured labels, and multi-select chips for `emotion` and `process_violation`.

**What goes away:** `chipLabel`'s slug-to-title derivation and its `SPECIAL` map (`{ market_thesis: 'Market / Thesis', pnl: 'P&L' }`). Labels come from config now. Deleting that function's body is part of the task — leaving it would give two sources of truth for a label.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_review_markers.py`:

```python
# ── Review chain ──────────────────────────────────────────────────────────────

def test_live_page_carries_the_configured_vocabulary(client, tmp_db):
    """The chips are built in JS from a payload the server renders. A renamed
    label must reach the page without a code change."""
    db.save_review_marker_group("process_violation", [
        {"key": "none", "label": "Clean", "at_entry": True},
        {"key": "overtraded", "label": "Traded too much", "at_entry": True},
    ])

    html = client.get("/live-v2").get_data(as_text=True)

    assert "Traded too much" in html
    assert '"key": "overtraded"' in html or '"key":"overtraded"' in html


def test_live_page_no_longer_derives_labels_from_slugs(client, tmp_db):
    """chipLabel used to title-case the stored key and special-case two of them.
    Two sources of truth for a label is how they drift."""
    html = client.get("/live-v2").get_data(as_text=True)

    assert "market_thesis: 'Market / Thesis'" not in html


def test_multi_groups_are_marked_multi_in_the_payload(client, tmp_db):
    html = client.get("/live-v2").get_data(as_text=True)

    assert '"multi": true' in html.lower() or '"multi":true' in html.lower()
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m pytest tests/test_review_markers.py -q`
Expected: the three new tests FAIL — the page has no vocabulary payload and still carries the `SPECIAL` map.

- [ ] **Step 3: Render the vocabulary into the page**

In `server.py`'s live-v2 view, add:

```python
                           review_markers_json=json.dumps(logic.get_review_markers()),
```

to the `render_template` call, without touching the existing kwargs. In `templates/live_v2.html`, near the other bootstrapped constants:

```javascript
const REVIEW_MARKERS = {{ review_markers_json|safe }};
const RM_BY_ID = Object.fromEntries(REVIEW_MARKERS.map(g => [g.id, g]));
```

- [ ] **Step 4: Replace the label derivation and the chip builders**

```javascript
    // Labels come from Settings → Tags → Review Markers. The old version
    // title-cased the stored key and special-cased two of them, which meant a
    // renamed option still rendered its slug.
    function chipLabel(field, value) {
      const g = RM_BY_ID[field];
      const t = g && g.tags.find(x => x.key === value);
      return t ? t.label : value;
    }

    // emotion and process_violation hold a list; the others hold one key.
    function chipSelected(field, value) {
      const current = field === 'management_issue' ? reviewMgmtIssue
        : field === 'emotion' ? reviewEmotion
        : field === 'process_violation' ? reviewViolation
        : field === 'management_driver' ? reviewDriver : '';
      return Array.isArray(current) ? current.indexOf(value) !== -1 : current === value;
    }

    function chipBtn(field, value) {
      return `<div class="rv2-chip${chipSelected(field, value) ? ' selected' : ''}"
        onclick="toggleReviewField(${trade.id}, '${field}', '${value}')">${chipLabel(field, value)}</div>`;
    }
```

Build each question's chips by iterating `RM_BY_ID[field].tags` rather than a hardcoded list.

- [ ] **Step 5: Add multi-select toggling with `none` exclusivity**

```javascript
// Single-select fields replace their value; multi-select fields toggle within a
// list. Choosing `none` clears the rest and choosing anything else clears
// `none` — "None plus Overtraded" is not a state worth recording.
function toggleReviewField(tradeId, field, value) {
  const group = RM_BY_ID[field];
  if (!group || !group.multi) return setReviewField(tradeId, field, value);

  const currentRaw = field === 'emotion' ? reviewEmotion : reviewViolation;
  let next = Array.isArray(currentRaw) ? currentRaw.slice() : (currentRaw ? [currentRaw] : []);
  const at = next.indexOf(value);
  if (at !== -1) {
    next.splice(at, 1);
  } else if (value === 'none') {
    next = ['none'];
  } else {
    next = next.filter(v => v !== 'none').concat([value]);
  }
  setReviewField(tradeId, field, next);
}
```

`setReviewField` already POSTs the value it is given; an array serialises through `JSON.stringify` unchanged, and Task 3's validation accepts both shapes. Confirm it does not coerce with `String(value)` before sending — if it does, pass the array through untouched.

- [ ] **Step 6: Initialise the selection state from stored lists**

Wherever `reviewEmotion` and `reviewViolation` are seeded from the trade, decode a JSON array:

```javascript
  // Stored as a JSON array of keys; older rows may still hold a bare string.
  function rmList(raw) {
    if (!raw) return [];
    if (Array.isArray(raw)) return raw;
    try { const p = JSON.parse(raw); return Array.isArray(p) ? p : [raw]; }
    catch (e) { return [raw]; }
  }
```

and use `rmList(trade.emotion)` / `rmList(trade.process_violation)`.

- [ ] **Step 7: Run the tests and watch them pass**

Run: `python3 -m pytest tests/test_review_markers.py -q`
Expected: 44 passed.

- [ ] **Step 8: Check the JavaScript parses**

```bash
python3 - <<'PY'
import re, subprocess, tempfile, os
s = open("templates/live_v2.html").read()
js = "\n".join(m for m in re.findall(r"<script[^>]*>(.*?)</script>", s, re.S) if "src=" not in m)
js = re.sub(r"\{\{.*?\}\}", "0", js); js = re.sub(r"\{%.*?%\}", "", js)
t = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False); t.write(js); t.close()
r = subprocess.run(["node", "--check", t.name], capture_output=True, text=True)
print("JS parse:", "OK" if r.returncode == 0 else "FAIL\n" + r.stderr[:600]); os.unlink(t.name)
PY
```

Expected: `JS parse: OK`.

- [ ] **Step 9: Mutation-check two tests**

1. Restore `chipLabel`'s `SPECIAL` map → `test_live_page_no_longer_derives_labels_from_slugs` must fail.
2. Remove `review_markers_json` from the render call → `test_live_page_carries_the_configured_vocabulary` must fail.

Report the observed outcome for each.

- [ ] **Step 10: Verify a full round trip against a COPY of the real journal**

```bash
SC="$(dirname "$(mktemp -u)")"; cp data/journal.db "$SC/rm2.db"
python3 - <<PY
import database as db
db.DB_PATH = "$SC/rm2.db"; db.init_db()
import server, app_logic as logic
server.app.config["TESTING"] = True
with server.app.test_client() as c:
    c.post("/api/settings/review-markers/process_violation", json={
        "tags": [{"key": "none", "label": "Clean", "at_entry": True},
                 {"key": "overtraded", "label": "Traded too much", "at_entry": True}],
        "multi": True})
    print("label after rename:", logic.marker_label("process_violation", "none"))
    print("A-grade rule still keyed off 'none':",
          logic.validate_assessment({"grade": "A", "process_violation": ["none"]})[1] is None)
    html = c.get("/live-v2").get_data(as_text=True)
    print("renamed label on the review page:", "Traded too much" in html)
    print("settings page:", c.get("/settings").status_code)
PY
```

Expected: the label reads `Clean`, the A-grade rule still passes on `none`, the renamed label appears on the review page, and Settings returns 200. Never point `DB_PATH` at `data/journal.db` itself.

- [ ] **Step 11: Bump the version and update the changelog**

```bash
echo "4.12.0" > VERSION
```

Add above the `## [4.11.1]` entry in `CHANGELOG.md`:

```markdown
## [4.12.0] — 2026-09-15

### Added

- **Review markers are configurable.** The five review vocabularies — How did you manage it, What
  primarily drove your management decisions, What changed, What were you feeling, and Process
  violation — are editable under Settings → Tags → **Review Markers**, a new second tab.
- **Emotions and process violations are multi-select.** A trade is rarely one feeling or one
  mistake. Choosing "None" clears the rest and choosing anything else clears "None".
- Each emotion carries an **offer at entry** flag, replacing the hardcoded rule that excluded the
  two fear states from the pre-entry question.

### Changed

- Each tag now has a stable key the code reads plus a label you can rename. Trades store the key,
  so renaming an option never touches stored data and never needs a cascade — the mechanism behind
  the 4.8.1 relabelling bug cannot apply to these groups.
- A locked option can be **renamed but not deleted**. Four are locked because the review logic reads
  them: both management states, and the "None" in What changed and Process violation.
- `management` accepts no new options. The code branches on exactly two states, so a third would be
  unreadable; its labels are still editable.

### Fixed

- **The Multi-select toggle in Settings now saves.** It has never persisted anything — the payload
  carried only the tag list and the card re-rendered from a hardcoded constant, so the switch moved
  and the setting was silently discarded. It now applies to the original tag groups too.
```

- [ ] **Step 12: Run the whole suite and commit**

```bash
python3 -m pytest tests/ -q
git add templates/live_v2.html server.py VERSION CHANGELOG.md tests/test_review_markers.py
git commit -m "feat: multi-select review chain reading the configured vocabulary"
```

**Do not push.**

---

## Human verification

No JavaScript test infrastructure exists in this repo, so these need eyes on screen:

1. Settings → Tags → **Review Markers** is the second tab and all five cards render.
2. Rename "None" under Process violation to "Clean", save, reload — the review chain shows "Clean",
   and grading a trade A with "Clean" selected still saves.
3. Delete an unlocked option, save, reload — it is gone from the review chain. The locked rows offer
   no ✕.
4. Add a new emotion, leave **entry** ticked, and confirm it appears on the pre-entry question; untick
   it, save, and confirm it disappears from entry but stays in the review.
5. Select two emotions on one trade, reload the page, and confirm both come back selected.
6. Select "None" under Process violation with another value already chosen — the other clears. Then
   pick a real violation and confirm "None" clears.
7. Toggle Multi-select off for Emotions, save, reload — the chips become single-select.
