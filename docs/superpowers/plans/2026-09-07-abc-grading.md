# A/B/C Grading & Diagnostic Tags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 5-point execution score with one trader-chosen A/B/C grade plus five diagnostic fields, and replace the peak-derived verdict labels with two neutral coloured ratios.

**Architecture:** Seven new scalar columns on `live_trades` and `trades`, carried across on push like the existing `mfe_*` and `market_state_json` fields. All analysis stays derived-on-read in `app_logic.py`. The retired machinery (5-point score, exit tag group, verdict roll-up) is left in the database and simply stops being read.

**Tech Stack:** Python 3.9.6, Flask, SQLite (stdlib `sqlite3`), server-rendered Jinja templates with vanilla JS. pytest (109 tests currently green).

**Spec:** `docs/superpowers/specs/2026-09-07-abc-grading-design.md` — read it first. Several choices look arbitrary without the framework sections it cites.

## Global Constraints

- **P&L has no vote.** No derived grade, no colour band, and no headline may use P&L as evidence of execution quality. The single exception is blanking the capture number on a loss, which is stated explicitly in the spec §5.1.
- **An early exit is not automatically a mistake.** No label may judge an exit from price data alone. This is why the verdict names are being removed.
- **Three-layer rule.** SQL only in `database.py`; business logic only in `app_logic.py`; `server.py` holds routes only.
- **Nothing derived is persisted.** Ratios, colour bands, distributions and cross-tabs are computed on read, every time.
- **Additive migrations only**, guarded, inside `init_db()`, which runs on **every request** and must stay safe to re-run forever. The one deletion in this plan (Task 6) is flag-guarded and one-shot.
- **Backward-compatible signatures**: new keyword arguments with defaults.
- **Commit straight to `main`.** Never branch, never open a PR.
- Runtime is **Python 3.9.6** — no 3.10+ syntax.
- **NULL means not recorded, and is never coerced.** Every distribution reports its own denominator.

### Exact values, copied from the spec

| Field | Values |
|---|---|
| `grade` | `A` \| `B` \| `C` \| NULL |
| `management` | `followed` \| `deviated` \| NULL |
| `management_issue` | `none` \| `early_exit` \| `late_exit` \| `stop_change` \| `overmanaged` \| `under_managed` \| `premature_scale_out` \| NULL |
| `emotion` | `calm` \| `fear_of_loss` \| `fear_of_giving_back` \| `greed` \| `frustration` \| `impatience` \| `overconfidence` \| `distracted` \| NULL |
| `emotion_entry` | the six that can precede a trade: `calm` \| `greed` \| `frustration` \| `impatience` \| `overconfidence` \| `distracted` \| NULL |
| `process_violation` | `none` \| `traded_outside_plan` \| `exceeded_risk` \| `revenge_trade` \| `overtraded` \| NULL |
| `pre_tags_late` | `0` \| `1` |

| Config key | Default | Meaning |
|---|---|---|
| `plan_capture_low` | 0.60 | existing — below this is `cut_early` |
| `plan_capture_mid` | 0.80 | **new** — capture colour split inside `at_plan` |
| `plan_capture_high` | 1.10 | existing — above this is `ran_past` |
| `target_fit_low` | 0.80 | **new** — below this, target too far |
| `target_fit_high` | 1.20 | **new** — above this, target too close |

### Real data conventions (verified — do not guess)

- `trades.direction` is `'Long'`/`'Short'`; `fills.side` is `'Buy'`/`'Sell'`.
- `live_trade_executions.exec_type` is mixed case — exit-side is the complement of `('OPEN','ADD')`.
- `db.update_live_trade(live_trade_id, **kwargs)` writes arbitrary columns — no signature change needed for the live side.
- `db.insert_trade(...)` has explicit keyword parameters and **does** need extending.
- `db.set_trade_tags(trade_id, group_id, tags)` replaces a group's tags for a trade.
- The assessment page and review page are both inside `templates/live_v2.html` (~9,400 lines). Anchors: process checklist ~4905, technical factors ~4911, mental state ~4920, `commitStrength()` button ~4932, `renderReviewCenter` ~5072, execution-score hero ~5166, the two review questions ~5194 and ~5206.
- `get_tag_groups()` returns the DB `tag_config` override **wholesale** when rows exist for a group. This is why Task 6 must delete rows, not just edit `TAG_GROUPS`.

---

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `tests/test_assessment.py` | Schema, DB layer, routes, validation, push carry-through for the seven fields |
| `tests/test_grade_analytics.py` | Target fit, capture bands, grade distribution, the B/C diagnostic block |

**Modified:**

| File | Change |
|---|---|
| `database.py` | 7 columns × 2 tables; `set_trade_assessment`; `insert_trade` kwargs; exit-group deletion migration |
| `app_logic.py` | Validation vocabularies; `compute_target_fit`; capture bands; payload rewrite; `TAG_GROUPS` edit; delete `exit_tag_signals` |
| `server.py` | Assessment save routes (live + journal side) |
| `templates/live_v2.html` | Assessment page: tile relabel, entry emotion, Setup/Pre-trade. Review page: grade chain replaces score hero and the two question blocks |
| `templates/weekly_review.html` | Grade distribution, P&L column, capture colours, target-fit distribution, delete fear headline, B/C block |
| `templates/day.html` | Trade trays show the letter grade |
| `SCHEMA.md`, `CHANGELOG.md`, `VERSION` | Documentation and version (project rules) |

**A note on testing the UI.** This project has no JavaScript test infrastructure and this plan does not add any. Tasks 7, 8, 9 and 10 therefore carry **manual verification steps** instead of automated ones. Everything computational lives in Python and is unit-tested; the templates stay thin. Follow the manual steps literally — they are the only safety net those tasks have.

---

## Task 1: Schema and DB layer

**Files:**
- Modify: `database.py` (migration block in `init_db()`; `insert_trade`; new function beside `update_trade_notes`)
- Modify: `SCHEMA.md`
- Test: `tests/test_assessment.py` (create)

**Interfaces:**
- Consumes: `tmp_db`, `client`, `day_id` fixtures from `tests/conftest.py`.
- Produces:
  - Seven columns on both `live_trades` and `trades`
  - `db.set_trade_assessment(trade_id, **fields)` — writes any subset of the seven onto a journal trade
  - `db.insert_trade(..., grade=None, management=None, management_issue=None, emotion=None, emotion_entry=None, process_violation=None, pre_tags_late=0)`

> Note on `emotion_entry`: the assessment page runs before the trade exists and writes to
> `trade_strength`; Task 7 copies the value onto the trade at creation. This task only creates the
> column — nothing writes it yet.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_assessment.py`:

```python
"""A/B/C grade and the five diagnostic fields.

Seven scalar columns rather than a JSON blob: every question the framework
asks is a GROUP BY over two of these, and the existing execution_score_json
is exactly the blob shape that makes those questions awkward.
"""
import database as db

ASSESSMENT_COLS = ["grade", "management", "management_issue", "emotion",
                   "emotion_entry", "process_violation", "pre_tags_late"]


def _cols(table):
    with db.get_conn() as conn:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def test_assessment_columns_exist_on_both_tables(tmp_db):
    for table in ("trades", "live_trades"):
        cols = _cols(table)
        for c in ASSESSMENT_COLS:
            assert c in cols, f"{c} missing from {table}"


def test_assessment_migration_is_rerunnable(tmp_db):
    db.init_db()
    db.init_db()
    assert _cols("trades").count("grade") == 1
    assert _cols("live_trades").count("emotion_entry") == 1


def test_assessment_fields_default_to_null(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40")
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    for c in ASSESSMENT_COLS[:-1]:
        assert row[c] is None, f"{c} should default to NULL, not a coerced value"
    assert row["pre_tags_late"] == 0


def test_insert_trade_accepts_the_assessment_fields(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40",
                               grade="B", management="deviated",
                               management_issue="early_exit",
                               emotion="fear_of_giving_back",
                               emotion_entry="calm",
                               process_violation="none",
                               pre_tags_late=1)
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    assert row["grade"] == "B"
    assert row["management"] == "deviated"
    assert row["management_issue"] == "early_exit"
    assert row["emotion"] == "fear_of_giving_back"
    assert row["emotion_entry"] == "calm"
    assert row["process_violation"] == "none"
    assert row["pre_tags_late"] == 1


def test_set_trade_assessment_writes_a_subset(tmp_db, day_id):
    """Diagnosis happens after the session, one field at a time."""
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40", grade="A")

    db.set_trade_assessment(trade_id, management="followed", emotion="calm")

    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    assert row["management"] == "followed"
    assert row["emotion"] == "calm"
    assert row["grade"] == "A", "untouched fields must survive a partial write"


def test_set_trade_assessment_ignores_unknown_fields(tmp_db, day_id):
    """The route passes a request body through; an unknown key must not
    become SQL."""
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40")
    db.set_trade_assessment(trade_id, grade="A", nonsense="x'; DROP TABLE trades;--")
    with db.get_conn() as conn:
        row = conn.execute("SELECT grade FROM trades WHERE id = ?", (trade_id,)).fetchone()
        assert row["grade"] == "A"
        assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1


def test_set_trade_assessment_with_no_known_fields_is_a_noop(tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40", grade="A")
    db.set_trade_assessment(trade_id, nonsense="x")
    with db.get_conn() as conn:
        assert conn.execute("SELECT grade FROM trades WHERE id = ?",
                            (trade_id,)).fetchone()["grade"] == "A"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_assessment.py -v`
Expected: FAIL — `assert 'grade' in cols` fails, and `AttributeError: module 'database' has no attribute 'set_trade_assessment'`.

- [ ] **Step 3: Add the migration**

In `database.py` `init_db()`, immediately after the `mfe_*` migration block added in 4.8.0:

```python
        # Migration: A/B/C grade and the five diagnostic fields. Scalar columns
        # rather than a JSON blob because every analytic question over them is a
        # GROUP BY on two fields; execution_score_json is the blob shape that
        # makes those questions awkward today. NULL means not recorded and is
        # never coerced — historical trades carry NULL and are reported as
        # uncovered rather than counted as something.
        _ASSESSMENT_COLS = [
            ("grade", "TEXT"),
            ("management", "TEXT"),
            ("management_issue", "TEXT"),
            ("emotion", "TEXT"),
            ("emotion_entry", "TEXT"),
            ("process_violation", "TEXT"),
            ("pre_tags_late", "INTEGER NOT NULL DEFAULT 0"),
        ]
        for _table in ("trades", "live_trades"):
            _existing = [r[1] for r in conn.execute(
                f"PRAGMA table_info({_table})").fetchall()]
            for _col, _decl in _ASSESSMENT_COLS:
                if _col not in _existing:
                    conn.execute(f"ALTER TABLE {_table} ADD COLUMN {_col} {_decl}")
```

- [ ] **Step 4: Extend `insert_trade`**

Locate `def insert_trade(` in `database.py` (currently ~line 1206). Add the seven keyword parameters with defaults after `market_state_json=None`, and add them to the column list and the `VALUES` tuple. The existing parameters and their order must not change — callers pass the first nine positionally.

```python
def insert_trade(day_id, trade_num, direction, qty, avg_entry, avg_exit, pnl,
                 entry_time, exit_time, is_open=False, execution_json=None,
                 execution_score_json=None, context_id=None, market_state_json=None,
                 grade=None, management=None, management_issue=None, emotion=None,
                 emotion_entry=None, process_violation=None, pre_tags_late=0):
```

Extend the `INSERT` statement's column list and placeholders to match, appending the seven in the same order.

- [ ] **Step 5: Add `set_trade_assessment`**

Beside `update_trade_notes` in `database.py`:

```python
_ASSESSMENT_FIELDS = ("grade", "management", "management_issue", "emotion",
                      "emotion_entry", "process_violation", "pre_tags_late")


def set_trade_assessment(trade_id, **fields):
    """Write any subset of the assessment fields onto a journal trade.

    Diagnosis happens after the session, often one field at a time, so a
    partial write must leave the others alone. Keys are filtered against a
    fixed allowlist because the caller is a route handler passing a request
    body through — an unknown key must never reach the SQL string.
    """
    known = {k: v for k, v in fields.items() if k in _ASSESSMENT_FIELDS}
    if not known:
        return
    sets = ", ".join(f"{k} = ?" for k in known)
    with get_conn() as conn:
        conn.execute(f"UPDATE trades SET {sets} WHERE id = ?",
                     list(known.values()) + [trade_id])
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_assessment.py -v`
Expected: all pass.

- [ ] **Step 7: Update `SCHEMA.md`**

In `### 3. TRADES`, add seven rows:

```
| grade              | TEXT    | Nullable. 'A' \| 'B' \| 'C'. The trader's judgement of which game they played. Never derived. |
| management         | TEXT    | Nullable. 'followed' \| 'deviated'. Everything after entry until flat, including the exit. |
| management_issue   | TEXT    | Nullable. none \| early_exit \| late_exit \| stop_change \| overmanaged \| under_managed \| premature_scale_out. Only meaningful when management='deviated'. |
| emotion            | TEXT    | Nullable. calm \| fear_of_loss \| fear_of_giving_back \| greed \| frustration \| impatience \| overconfidence \| distracted. Recorded at review. |
| emotion_entry      | TEXT    | Nullable. Same vocabulary minus the two fear states, which require an open position. Recorded at entry. |
| process_violation  | TEXT    | Nullable. none \| traded_outside_plan \| exceeded_risk \| revenge_trade \| overtraded. Only asked when grade is B or C. |
| pre_tags_late      | INTEGER | NOT NULL DEFAULT 0. 1 when pre-trade tags were first filled at review rather than at entry. |
```

Add below the table:

```
> P&L has no vote on `grade`: a losing trade can be A-game and a profitable trade can be C-game.
> `execution_score_json` is retained for historical trades but is no longer written or read.
> The same seven columns exist on `live_trades` and are carried across on push.
```

In `### 9. LIVE_TRADES`, note the same seven columns exist and are carried to `trades` on push.

- [ ] **Step 8: Run the full suite**

Run: `python3 -m pytest tests/ -v`
Expected: all pass (109 existing + 7 new).

- [ ] **Step 9: Commit**

```bash
git add database.py SCHEMA.md tests/test_assessment.py
git commit -m "feat: add A/B/C grade and diagnostic columns

Seven scalar columns on trades and live_trades rather than a JSON blob,
because every question the framework asks is a GROUP BY over two of them.
set_trade_assessment filters keys against a fixed allowlist since its caller
passes a request body straight through."
```

---

## Task 2: Validation and routes

**Files:**
- Modify: `app_logic.py` (vocabularies + `validate_assessment`)
- Modify: `server.py` (two routes)
- Test: `tests/test_assessment.py`

**Interfaces:**
- Consumes: `db.set_trade_assessment` (Task 1), `db.update_live_trade(**kwargs)` (existing).
- Produces:
  - `logic.GRADES`, `logic.MANAGEMENT`, `logic.MANAGEMENT_ISSUES`, `logic.EMOTIONS`, `logic.ENTRY_EMOTIONS`, `logic.PROCESS_VIOLATIONS` — tuples of valid values
  - `logic.validate_assessment(fields) -> (cleaned_dict, error_or_None)`
  - `POST /api/live/<live_id>/assessment` and `POST /api/trade/<trade_id>/assessment`, both accepting any subset of the seven fields

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_assessment.py`:

```python
import app_logic as logic


def test_vocabularies_match_the_spec():
    assert logic.GRADES == ("A", "B", "C")
    assert logic.MANAGEMENT == ("followed", "deviated")
    assert logic.MANAGEMENT_ISSUES == (
        "none", "early_exit", "late_exit", "stop_change",
        "overmanaged", "under_managed", "premature_scale_out")
    assert logic.EMOTIONS == (
        "calm", "fear_of_loss", "fear_of_giving_back", "greed",
        "frustration", "impatience", "overconfidence", "distracted")
    assert logic.PROCESS_VIOLATIONS == (
        "none", "traded_outside_plan", "exceeded_risk", "revenge_trade", "overtraded")


def test_entry_emotions_exclude_the_two_that_need_an_open_position():
    """Fear of loss and fear of giving back cannot precede a trade."""
    assert "fear_of_loss" not in logic.ENTRY_EMOTIONS
    assert "fear_of_giving_back" not in logic.ENTRY_EMOTIONS
    assert set(logic.ENTRY_EMOTIONS) < set(logic.EMOTIONS)
    assert len(logic.ENTRY_EMOTIONS) == 6


def test_validate_accepts_a_good_payload():
    cleaned, err = logic.validate_assessment(
        {"grade": "B", "management": "deviated", "management_issue": "early_exit",
         "emotion": "fear_of_giving_back", "process_violation": "revenge_trade"})
    assert err is None
    assert cleaned["grade"] == "B"


def test_validate_rejects_a_value_outside_its_vocabulary():
    _, err = logic.validate_assessment({"grade": "D"})
    assert err is not None and "grade" in err


def test_validate_rejects_management_issue_without_deviated():
    """The issue describes what the deviation was; it is meaningless otherwise."""
    _, err = logic.validate_assessment(
        {"management": "followed", "management_issue": "early_exit"})
    assert err is not None and "management_issue" in err


def test_validate_allows_management_issue_none_when_followed():
    cleaned, err = logic.validate_assessment(
        {"management": "followed", "management_issue": "none"})
    assert err is None
    assert cleaned["management_issue"] == "none"


def test_validate_rejects_a_process_violation_on_an_a_grade():
    """The field is only asked on B or C; an A-game violation is a contradiction."""
    _, err = logic.validate_assessment(
        {"grade": "A", "process_violation": "revenge_trade"})
    assert err is not None and "process_violation" in err


def test_validate_allows_process_violation_none_on_an_a_grade():
    cleaned, err = logic.validate_assessment({"grade": "A", "process_violation": "none"})
    assert err is None


def test_validate_rejects_a_fear_emotion_at_entry():
    _, err = logic.validate_assessment({"emotion_entry": "fear_of_giving_back"})
    assert err is not None and "emotion_entry" in err


def test_validate_drops_unknown_keys_without_erroring():
    cleaned, err = logic.validate_assessment({"grade": "A", "sneaky": "value"})
    assert err is None
    assert "sneaky" not in cleaned


def test_validate_accepts_an_empty_payload():
    cleaned, err = logic.validate_assessment({})
    assert err is None and cleaned == {}


def test_post_assessment_to_a_journal_trade(client, tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40")
    res = client.post(f"/api/trade/{trade_id}/assessment",
                      json={"grade": "A", "management": "followed", "emotion": "calm"})
    assert res.status_code == 200
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    assert (row["grade"], row["management"], row["emotion"]) == ("A", "followed", "calm")


def test_post_assessment_rejects_an_invalid_value(client, tmp_db, day_id):
    trade_id = db.insert_trade(day_id, 1, "Long", 3, 7756.0, 7795.5, 1035.0,
                               "10:05", "10:40")
    res = client.post(f"/api/trade/{trade_id}/assessment", json={"grade": "D"})
    assert res.status_code == 400
    with db.get_conn() as conn:
        assert conn.execute("SELECT grade FROM trades WHERE id = ?",
                            (trade_id,)).fetchone()["grade"] is None


def test_post_assessment_to_a_live_trade(client, tmp_db):
    live_id = db.create_live_trade(None, "Long", "MES", 7756.0, "10:05", 3, "full")
    res = client.post(f"/api/live/{live_id}/assessment",
                      json={"grade": "C", "process_violation": "revenge_trade"})
    assert res.status_code == 200
    lt = db.get_live_trade(live_id)
    assert lt["grade"] == "C"
    assert lt["process_violation"] == "revenge_trade"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_assessment.py -k "vocab or validate or post_assessment" -v`
Expected: FAIL — `AttributeError: module 'app_logic' has no attribute 'GRADES'`.

- [ ] **Step 3: Add the vocabularies and validator**

In `app_logic.py`, after `get_plan_check_from_date()`:

```python
# ── Trade assessment vocabularies ────────────────────────────────────────────
# One A/B/C grade plus a small number of diagnostic tags. The grade is always
# the trader's judgement — never derived — because a formula cannot see which
# version of them showed up, and P&L has no vote either way.

GRADES = ("A", "B", "C")
MANAGEMENT = ("followed", "deviated")
MANAGEMENT_ISSUES = ("none", "early_exit", "late_exit", "stop_change",
                     "overmanaged", "under_managed", "premature_scale_out")
EMOTIONS = ("calm", "fear_of_loss", "fear_of_giving_back", "greed",
            "frustration", "impatience", "overconfidence", "distracted")
# Fear of loss and fear of giving back both require an open position, so
# offering them before entry invites a nonsense answer.
ENTRY_EMOTIONS = tuple(e for e in EMOTIONS
                       if e not in ("fear_of_loss", "fear_of_giving_back"))
PROCESS_VIOLATIONS = ("none", "traded_outside_plan", "exceeded_risk",
                      "revenge_trade", "overtraded")

_ASSESSMENT_VOCAB = {
    "grade": GRADES,
    "management": MANAGEMENT,
    "management_issue": MANAGEMENT_ISSUES,
    "emotion": EMOTIONS,
    "emotion_entry": ENTRY_EMOTIONS,
    "process_violation": PROCESS_VIOLATIONS,
}


def validate_assessment(fields):
    """Clean and check an assessment payload.

    Returns (cleaned, error). `cleaned` holds only known keys with valid
    values; `error` is a human-readable string or None. Unknown keys are
    dropped silently rather than rejected — the caller is a form post that
    may carry extra state — but a known key with a bad value is an error,
    because silently discarding it would lose data the trader entered.
    """
    cleaned = {}
    for key, vocab in _ASSESSMENT_VOCAB.items():
        if key not in fields:
            continue
        value = fields[key]
        if value in (None, ""):
            cleaned[key] = None
            continue
        if value not in vocab:
            return {}, f"{key} must be one of {', '.join(vocab)}"
        cleaned[key] = value

    if "pre_tags_late" in fields:
        cleaned["pre_tags_late"] = 1 if fields["pre_tags_late"] else 0

    # A management issue describes what the deviation was, so it is meaningless
    # without one. 'none' is always allowed.
    issue = cleaned.get("management_issue")
    if issue and issue != "none" and cleaned.get("management") != "deviated":
        return {}, "management_issue requires management to be 'deviated'"

    # The violation field is only asked on a B or C grade.
    violation = cleaned.get("process_violation")
    if violation and violation != "none" and cleaned.get("grade") == "A":
        return {}, "process_violation cannot be set on an A grade"

    return cleaned, None
```

- [ ] **Step 4: Add the two routes**

In `server.py`, after `api_save_trade_mfe`:

```python
@app.route("/api/trade/<int:trade_id>/assessment", methods=["POST"])
def api_save_trade_assessment(trade_id):
    """Record the A/B/C grade and diagnostic fields on a journal trade."""
    cleaned, err = logic.validate_assessment(request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    db.set_trade_assessment(trade_id, **cleaned)
    return jsonify({"ok": True})


@app.route("/api/live/<int:live_id>/assessment", methods=["POST"])
def api_save_live_assessment(live_id):
    """Same fields on a live trade, before it is pushed to the journal."""
    cleaned, err = logic.validate_assessment(request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    if cleaned:
        db.update_live_trade(live_id, **cleaned)
    return jsonify({"ok": True})
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_assessment.py -v`
Expected: all pass.

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest tests/ -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app_logic.py server.py tests/test_assessment.py
git commit -m "feat: assessment vocabularies, validation and routes

Two cross-field rules are enforced server-side rather than only hidden in
the UI: a management issue requires management='deviated', and a process
violation cannot sit on an A grade. Entry emotion excludes the two fear
states, which require an open position."
```

---

## Task 3: Push carry-through

**Files:**
- Modify: `app_logic.py` (`close_live_trade_to_journal`, the `db.insert_trade(...)` call)
- Test: `tests/test_assessment.py`

**Interfaces:**
- Consumes: `db.insert_trade` with the seven kwargs (Task 1).
- Produces: journal trades carrying the assessment recorded live-side.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_assessment.py`:

```python
def test_push_carries_the_assessment_to_the_journal(client, tmp_db):
    live_id = db.create_live_trade(None, "Long", "MES", 7756.0, "10:05", 3, "full")
    db.add_live_trade_execution(live_id, "OPEN", 1, 3, 7756.0, "10:05", 0.0)
    db.add_live_trade_execution(live_id, "EXIT", 1, 3, 7786.0, "10:40", 450.0)
    db.update_live_trade(live_id, grade="B", management="deviated",
                         management_issue="early_exit",
                         emotion="fear_of_giving_back", emotion_entry="impatience",
                         process_violation="none", pre_tags_late=1)

    trade_id = logic.close_live_trade_to_journal(live_id)

    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    assert row["grade"] == "B"
    assert row["management"] == "deviated"
    assert row["management_issue"] == "early_exit"
    assert row["emotion"] == "fear_of_giving_back"
    assert row["emotion_entry"] == "impatience"
    assert row["process_violation"] == "none"
    assert row["pre_tags_late"] == 1


def test_push_of_an_ungraded_trade_leaves_the_fields_null(tmp_db):
    live_id = db.create_live_trade(None, "Long", "MES", 7756.0, "10:05", 3, "full")
    db.add_live_trade_execution(live_id, "OPEN", 1, 3, 7756.0, "10:05", 0.0)
    db.add_live_trade_execution(live_id, "EXIT", 1, 3, 7786.0, "10:40", 450.0)

    trade_id = logic.close_live_trade_to_journal(live_id)

    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    assert row["grade"] is None
    assert row["pre_tags_late"] == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_assessment.py -k push_carries -v`
Expected: FAIL — `assert None == 'B'`.

- [ ] **Step 3: Carry the fields on push**

In `app_logic.py`, extend the `db.insert_trade(...)` call inside `close_live_trade_to_journal`, after `market_state_json=lt.get("market_state_json"),`:

```python
        grade=lt.get("grade"),
        management=lt.get("management"),
        management_issue=lt.get("management_issue"),
        emotion=lt.get("emotion"),
        emotion_entry=lt.get("emotion_entry"),
        process_violation=lt.get("process_violation"),
        pre_tags_late=lt.get("pre_tags_late") or 0,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_assessment.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app_logic.py tests/test_assessment.py
git commit -m "feat: carry the trade assessment onto the journal trade on push"
```

---

## Task 4: Target fit and capture colour bands

**Files:**
- Modify: `app_logic.py` (config accessors and two pure functions, beside `classify_bucket`)
- Test: `tests/test_grade_analytics.py` (create)

**Interfaces:**
- Consumes: `_dir_sign`, `PLAN_EPSILON`, `_config_float` (all existing in `app_logic.py`).
- Produces:
  - `logic.get_target_fit_bounds() -> (low, high)` — defaults `(0.80, 1.20)`
  - `logic.get_plan_capture_mid() -> float` — default `0.80`
  - `logic.compute_target_fit(direction, avg_entry, target, mfe_price) -> float | None`
  - `logic.classify_target_fit(target_fit, bounds=None) -> 'too_far' | 'calibrated' | 'too_close' | None`
  - `logic.capture_band(capture, pnl) -> 'red' | 'orange' | 'green' | 'blue' | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_grade_analytics.py`:

```python
"""Two ratios, neither carrying a verdict word.

  capture    = exit vs target   -- did I wait for my plan?      (behaviour)
  target_fit = peak vs target   -- was my plan reasonable?      (calibration)

The framework is explicit that an early exit is only a mistake if unjustified
by process, never merely because price continued afterwards. So these describe;
the trader's grade judges.
"""
import database as db
import app_logic as logic


# ── compute_target_fit ───────────────────────────────────────────────────────

def test_target_fit_is_one_when_the_peak_lands_exactly_on_the_target():
    assert logic.compute_target_fit("Long", 7761.0, 7800.5, 7800.5) == 1.0


def test_target_fit_below_one_when_the_peak_fell_short():
    # planned 39.5 pts, peak reached 19.75 -> 0.5
    assert logic.compute_target_fit("Long", 7761.0, 7800.5, 7780.75) == 0.5


def test_target_fit_above_one_when_the_peak_ran_past():
    fit = logic.compute_target_fit("Long", 7761.0, 7800.5, 7820.25)
    assert round(fit, 4) == 1.5


def test_target_fit_is_direction_aware_for_shorts():
    # short: entry 7800, target 7760 (40 pts), peak 7780 is half way
    assert logic.compute_target_fit("Short", 7800.0, 7760.0, 7780.0) == 0.5
    # a peak BELOW the short target has run past it
    assert logic.compute_target_fit("Short", 7800.0, 7760.0, 7740.0) == 1.5


def test_target_fit_is_none_without_a_peak_or_target():
    assert logic.compute_target_fit("Long", 7761.0, 7800.5, None) is None
    assert logic.compute_target_fit("Long", 7761.0, None, 7800.5) is None


def test_target_fit_is_none_when_the_target_sits_within_a_tick_of_entry():
    assert logic.compute_target_fit("Long", 7761.0, 7761.1, 7800.0) is None


# ── classify_target_fit ──────────────────────────────────────────────────────

def test_target_fit_boundaries_with_the_default_bounds():
    b = (0.80, 1.20)
    assert logic.classify_target_fit(None, b) is None
    assert logic.classify_target_fit(0.50, b) == "too_far"
    assert logic.classify_target_fit(0.7999, b) == "too_far"
    assert logic.classify_target_fit(0.80, b) == "calibrated"
    assert logic.classify_target_fit(1.00, b) == "calibrated"
    assert logic.classify_target_fit(1.20, b) == "calibrated"
    assert logic.classify_target_fit(1.2001, b) == "too_close"


def test_target_fit_bounds_are_configurable(tmp_db):
    db.set_config("target_fit_low", "0.50")
    db.set_config("target_fit_high", "2.00")
    assert logic.get_target_fit_bounds() == (0.50, 2.00)
    assert logic.classify_target_fit(0.60) == "calibrated"


def test_target_fit_bounds_fall_back_when_config_is_junk(tmp_db):
    db.set_config("target_fit_low", "")
    db.set_config("target_fit_high", "nonsense")
    assert logic.get_target_fit_bounds() == (0.80, 1.20)


# ── capture_band ─────────────────────────────────────────────────────────────

def test_capture_bands_at_the_boundaries(tmp_db):
    assert logic.capture_band(0.10, 100.0) == "red"
    assert logic.capture_band(0.5999, 100.0) == "red"
    assert logic.capture_band(0.60, 100.0) == "orange"
    assert logic.capture_band(0.7999, 100.0) == "orange"
    assert logic.capture_band(0.80, 100.0) == "green"
    assert logic.capture_band(1.10, 100.0) == "green"
    assert logic.capture_band(1.1001, 100.0) == "blue"


def test_capture_band_is_blank_on_a_loss(tmp_db):
    """A capture ratio on a loser compares an exit against a target that was
    never in play."""
    assert logic.capture_band(0.90, -250.0) is None


def test_capture_band_renders_on_a_scratch(tmp_db):
    """A scratch is not a loss."""
    assert logic.capture_band(0.90, 0.0) == "green"


def test_capture_band_is_none_without_a_capture(tmp_db):
    assert logic.capture_band(None, 100.0) is None


def test_capture_mid_is_configurable(tmp_db):
    db.set_config("plan_capture_mid", "0.95")
    assert logic.get_plan_capture_mid() == 0.95
    assert logic.capture_band(0.90, 100.0) == "orange"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_grade_analytics.py -v`
Expected: FAIL — `AttributeError: module 'app_logic' has no attribute 'compute_target_fit'`.

- [ ] **Step 3: Implement the accessors and functions**

In `app_logic.py`, immediately after `classify_bucket`:

```python
# The capture colour split inside at_plan: "scraped it" vs "took it". The
# bucket boundaries themselves are unchanged; this only divides one of them.
DEFAULT_PLAN_CAPTURE_MID = 0.80

# Target fit bounds: how close the peak came to the planned exit.
DEFAULT_TARGET_FIT_LOW = 0.80
DEFAULT_TARGET_FIT_HIGH = 1.20


def get_plan_capture_mid():
    return _config_float("plan_capture_mid", DEFAULT_PLAN_CAPTURE_MID)


def get_target_fit_bounds():
    """(low, high) — below low the target was too far, above high too close."""
    return (_config_float("target_fit_low", DEFAULT_TARGET_FIT_LOW),
            _config_float("target_fit_high", DEFAULT_TARGET_FIT_HIGH))


def compute_target_fit(direction, avg_entry, target, mfe_price):
    """How far the peak got, as a share of the planned move.

    1.0 means price reached the target exactly. This asks whether the PLAN was
    reasonable, which is a different question from whether the trader waited
    for it — that is `compute_capture`. Read one row at a time it is hindsight;
    read across many trades it is calibration.
    """
    if target is None or mfe_price is None or avg_entry is None:
        return None
    sign = _dir_sign(direction)
    planned = sign * (float(target) - float(avg_entry))
    if abs(planned) < PLAN_EPSILON:
        return None
    return (sign * (float(mfe_price) - float(avg_entry))) / planned


def classify_target_fit(target_fit, bounds=None):
    if target_fit is None:
        return None
    low, high = get_target_fit_bounds() if bounds is None else bounds
    if target_fit < low:
        return "too_far"
    if target_fit <= high:
        return "calibrated"
    return "too_close"


def capture_band(capture, pnl):
    """Colour band for the capture number, or None to render it blank.

    Blank on a loss: the ratio compares an exit against a target that was never
    in play. A scratch (pnl == 0) is not a loss and still renders.
    """
    if capture is None:
        return None
    try:
        if float(pnl or 0) < 0:
            return None
    except (TypeError, ValueError):
        return None
    low, high = get_plan_capture_bounds()
    mid = get_plan_capture_mid()
    if capture < low:
        return "red"
    if capture < mid:
        return "orange"
    if capture <= high:
        return "green"
    return "blue"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_grade_analytics.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app_logic.py tests/test_grade_analytics.py
git commit -m "feat: target fit ratio and capture colour bands

Two ratios that separate 'did I wait for my plan' from 'was my plan
reasonable'. Neither carries a verdict word — the framework is explicit that
an early exit is only a mistake if unjustified by process, so price data
describes and the trader's grade judges."
```

---

## Task 5: Payload rewrite

Removes the verdict machinery and adds the new fields to `build_plan_execution`.

**Files:**
- Modify: `app_logic.py` (`build_plan_execution`)
- Test: `tests/test_grade_analytics.py`, `tests/test_plan_analysis.py`

**Interfaces:**
- Consumes: `compute_target_fit`, `classify_target_fit`, `capture_band` (Task 4); the assessment columns (Task 1).
- Produces: `build_plan_execution(trades)` returning rows with **added** `grade`, `management`, `management_issue`, `emotion`, `emotion_entry`, `process_violation`, `target_fit`, `target_fit_class`, `capture_band`, and **removed** `verdict`, `target_offered`, `tag_conflict`, `tag_suggestion`. Summary gains `grades`, `graded_of`, `target_fit_dist`, `bc_diagnosis`; loses `verdicts`, `verdicts_of`, `fear`, `greed`, `realism`.

**A spec ambiguity resolved here.** §8 does not list `realism` as retired, but §7's weekly layout does not include it either. `realism` reports the share of covered trades where the target was ever offered — which is exactly `target_fit >= 1.0`, measured more coarsely. Keeping both would put two overlapping percentages on the same page, the "two denominators both called covered" problem this project has already had once. **Ruling: retire `realism`; the target-fit distribution replaces it.**

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_grade_analytics.py`:

```python
import json


def _seed(day_id, num, direction="Long", entry=7761.0, exit_=7795.5, pnl=1035.0,
          fills=((3, 7756.0, 7736.0, 7786.0), (3, 7766.0, 7746.0, 7815.0)),
          **assessment):
    qty = sum(f[0] for f in fills)
    trade_id = db.insert_trade(day_id, num, direction, qty, entry, exit_, pnl,
                               "10:05", "10:40",
                               execution_json=json.dumps({"instrument": "MES"}),
                               **assessment)
    entry_side = "Buy" if direction == "Long" else "Sell"
    exit_side = "Sell" if direction == "Long" else "Buy"
    for q, price, stop, target in fills:
        db.insert_fill(trade_id, "10:05", entry_side, q, price,
                       stop_price=stop, stop_source="entered",
                       target_price=target, target_source="entered")
    db.insert_fill(trade_id, "10:40", exit_side, qty, exit_, exit_type="manual_exit")
    return trade_id


def _rows(day="2026-09-07"):
    return logic.build_plan_execution(db.get_trades_in_range(None, day, day))


def test_rows_carry_the_assessment_fields(tmp_db):
    day_id = db.upsert_day("2026-09-07", None)
    _seed(day_id, 1, grade="B", management="deviated",
          management_issue="early_exit", emotion="fear_of_giving_back")

    row = _rows()["rows"][0]

    assert row["grade"] == "B"
    assert row["management"] == "deviated"
    assert row["management_issue"] == "early_exit"
    assert row["emotion"] == "fear_of_giving_back"


def test_rows_carry_target_fit_and_capture_band(tmp_db):
    day_id = db.upsert_day("2026-09-07", None)
    tid = _seed(day_id, 1)
    db.set_trade_mfe(tid, 7809.5, "after", 30)

    row = _rows()["rows"][0]

    assert round(row["target_fit"], 4) == 1.2278   # (7809.5-7761)/(7800.5-7761)
    assert row["target_fit_class"] == "too_close"
    assert row["capture_band"] == "green"           # capture 0.873, profitable


def test_the_verdict_machinery_is_gone(tmp_db):
    """Removed by design: these judged an exit from price data alone."""
    day_id = db.upsert_day("2026-09-07", None)
    tid = _seed(day_id, 1)
    db.set_trade_mfe(tid, 7809.5, "after", 30)

    result = _rows()
    row = result["rows"][0]

    for gone in ("verdict", "target_offered", "tag_conflict", "tag_suggestion"):
        assert gone not in row, f"{gone} should have been removed from the row"
    for gone in ("verdicts", "verdicts_of", "fear", "greed", "realism"):
        assert gone not in result["summary"], f"{gone} should have been removed"


def test_summary_reports_the_grade_distribution_and_its_denominator(tmp_db):
    day_id = db.upsert_day("2026-09-07", None)
    _seed(day_id, 1, grade="A", pnl=500.0)
    _seed(day_id, 2, grade="B", pnl=-200.0)
    _seed(day_id, 3, grade="B", pnl=300.0)
    _seed(day_id, 4)                      # ungraded

    s = _rows()["summary"]

    assert s["grades"]["A"]["count"] == 1
    assert s["grades"]["B"]["count"] == 2
    assert s["grades"]["C"]["count"] == 0
    assert s["grades"]["B"]["net"] == 100.0
    assert s["graded_of"] == 3, "denominator is graded trades, not all trades"


def test_grade_distribution_ignores_pnl_as_evidence(tmp_db):
    """P&L has no vote: a losing trade can be A-game."""
    day_id = db.upsert_day("2026-09-07", None)
    _seed(day_id, 1, grade="A", pnl=-400.0)

    s = _rows()["summary"]

    assert s["grades"]["A"]["count"] == 1
    assert s["grades"]["A"]["net"] == -400.0


def test_summary_reports_the_target_fit_distribution(tmp_db):
    day_id = db.upsert_day("2026-09-07", None)
    a = _seed(day_id, 1)
    b = _seed(day_id, 2)
    c = _seed(day_id, 3)
    db.set_trade_mfe(a, 7770.0, "during", 30)    # fit 0.23 -> too_far
    db.set_trade_mfe(b, 7800.0, "after", 30)     # fit 0.987 -> calibrated
    db.set_trade_mfe(c, 7830.0, "after", 30)     # fit 1.747 -> too_close

    d = _rows()["summary"]["target_fit_dist"]

    assert d["too_far"] == 1
    assert d["calibrated"] == 1
    assert d["too_close"] == 1
    assert d["of"] == 3


def test_target_fit_counts_a_losing_trade(tmp_db):
    """Capture is blanked on a loss; target fit is not. 'Was my target
    reasonable' is a fair question on a loser."""
    day_id = db.upsert_day("2026-09-07", None)
    tid = _seed(day_id, 1, exit_=7740.0, pnl=-630.0)
    db.set_trade_mfe(tid, 7800.0, "during", 30)

    row = _rows()["rows"][0]
    assert row["capture_band"] is None
    assert row["target_fit_class"] == "calibrated"
    assert _rows()["summary"]["target_fit_dist"]["of"] == 1


def test_bc_diagnosis_names_the_commonest_issue_and_emotion(tmp_db):
    day_id = db.upsert_day("2026-09-07", None)
    _seed(day_id, 1, grade="B", management="deviated",
          management_issue="early_exit", emotion="fear_of_giving_back")
    _seed(day_id, 2, grade="C", management="deviated",
          management_issue="early_exit", emotion="frustration")
    _seed(day_id, 3, grade="B", management="deviated",
          management_issue="stop_change", emotion="fear_of_giving_back")
    _seed(day_id, 4, grade="A", management="followed",
          management_issue="none", emotion="calm")

    d = _rows()["summary"]["bc_diagnosis"]

    assert d["of"] == 3, "A-game trades are not part of the diagnosis"
    assert d["top_issue"] == ("early_exit", 2)
    assert d["top_emotion"] == ("fear_of_giving_back", 2)


def test_bc_diagnosis_is_empty_when_the_week_has_no_b_or_c(tmp_db):
    day_id = db.upsert_day("2026-09-07", None)
    _seed(day_id, 1, grade="A", management="followed", emotion="calm")

    d = _rows()["summary"]["bc_diagnosis"]

    assert d["of"] == 0
    assert d["top_issue"] is None
    assert d["top_emotion"] is None


def test_empty_week_produces_no_distributions(tmp_db):
    result = logic.build_plan_execution([])
    assert result["rows"] == []
    assert result["summary"]["graded_of"] == 0
    assert result["summary"]["target_fit_dist"]["of"] == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_grade_analytics.py -k "rows_carry or verdict_machinery or summary_reports or bc_diagnosis" -v`
Expected: FAIL — `KeyError: 'grade'` and `assert 'verdict' not in row`.

- [ ] **Step 3: Rewrite the row construction**

In `build_plan_execution`, in the per-trade loop:

- **Delete** the `offered = target_was_offered(...)` line, the `tag_signals = exit_tag_signals(...)` line, and the `"target_offered"`, `"tag_conflict"`, `"tag_suggestion"`, `"verdict"` and `"exit_tag"` entries from the row dict.
- **Add** to the row dict:

```python
            "grade": t.get("grade"),
            "management": t.get("management"),
            "management_issue": t.get("management_issue"),
            "emotion": t.get("emotion"),
            "emotion_entry": t.get("emotion_entry"),
            "process_violation": t.get("process_violation"),
            "target_fit": target_fit,
            "target_fit_class": classify_target_fit(target_fit, fit_bounds),
            "capture_band": capture_band(capture, t.get("pnl")),
```

with these computed just above the `rows.append(`:

```python
        target_fit = compute_target_fit(t.get("direction"), t.get("avg_entry"),
                                        target, mfe_price)
```

and `fit_bounds = get_target_fit_bounds()` hoisted beside the existing `bounds = get_plan_capture_bounds()` at the top of the function, so neither is read per row.

- [ ] **Step 4: Rewrite the summary**

Delete the `verdicts`, `fear_caps`, `greed_rows`, `offered`/`of_covered` accumulation and the `"verdicts"`, `"verdicts_of"`, `"fear"`, `"greed"`, `"realism"` keys. Add:

```python
    grades = {g: {"count": 0, "net": 0.0} for g in GRADES}
    fit_dist = {"too_far": 0, "calibrated": 0, "too_close": 0, "of": 0}
    bc_issues, bc_emotions, bc_count = {}, {}, 0

    for r in rows:
        pnl = float(r["pnl"] or 0)
        if r["grade"] in grades:
            grades[r["grade"]]["count"] += 1
            grades[r["grade"]]["net"] += pnl
        cls = r["target_fit_class"]
        if cls:
            fit_dist[cls] += 1
            fit_dist["of"] += 1
        if r["grade"] in ("B", "C"):
            bc_count += 1
            if r["management_issue"] and r["management_issue"] != "none":
                bc_issues[r["management_issue"]] = bc_issues.get(r["management_issue"], 0) + 1
            if r["emotion"]:
                bc_emotions[r["emotion"]] = bc_emotions.get(r["emotion"], 0) + 1

    for g in grades:
        grades[g]["net"] = round(grades[g]["net"], 2)

    def _top(counts):
        if not counts:
            return None
        key = max(counts, key=lambda k: (counts[k], k))
        return (key, counts[key])
```

and in the returned summary dict, replacing the removed keys:

```python
            "grades": grades,
            "graded_of": sum(g["count"] for g in grades.values()),
            "target_fit_dist": fit_dist,
            "bc_diagnosis": {"of": bc_count,
                             "top_issue": _top(bc_issues),
                             "top_emotion": _top(bc_emotions)},
```

Keep `capture_low`/`capture_high`, `window_minutes`, `buckets`, `no_plan`, `coverage`, `give_back`, `missed_run` exactly as they are.

- [ ] **Step 5: Delete the now-orphaned tests**

In `tests/test_plan_analysis.py`, remove the tests that assert on the removed machinery: everything in the `classify_verdict` and `exit_tag_signals` groups, plus `test_summary_verdicts_are_counted_over_the_covered_set_only`, `test_summary_target_realism_uses_the_covered_set`, and `test_build_plan_execution_applies_the_peak`'s verdict assertions. Keep every test of `weighted_plan_price`, `compute_capture`, `classify_bucket`, `compute_excursion`, coverage and the weekly payload — those still describe live behaviour.

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest tests/ -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app_logic.py tests/
git commit -m "feat: grade and target fit in the plan-execution payload

Removes the verdict roll-up (froze/bailed/didn't pay), the fear and greed
headlines and the tag-vs-peak reconciliation: all of them judged an exit from
price data alone, which the framework forbids. Target fit replaces realism,
which measured the same thing more coarsely — keeping both would put two
overlapping percentages on one page."
```

---

## Task 6: Retire the exit tag vocabulary

**Files:**
- Modify: `app_logic.py` (`TAG_GROUPS`; delete `exit_tag_signals`)
- Modify: `database.py` (one-shot deletion migration in `init_db()`)
- Test: `tests/test_tag_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `get_tag_groups()` no longer returns an `exit` group.

**The one destructive step in this plan.** `get_tag_groups()` returns the DB `tag_config` override wholesale when rows exist, so removing the group from `TAG_GROUPS` alone would leave the retired vocabulary still being served. The rows must go too.

**Ordering matters.** Version 4.8.2 added a one-shot, flag-guarded migration that *appends* the widened exit vocabulary into `tag_config`. This deletion must run **after** it and must not clear its flag — otherwise on a fresh database the append would re-add exactly what this removes, on the next request, forever.

**Do not route the deletion through `save_tag_config`.** It opens its own connection and would deadlock inside `init_db()`'s write transaction.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tag_config.py`:

```python
import app_logic as logic


def test_exit_group_is_gone_from_the_defaults():
    assert not any(g["id"] == "exit" for g in logic.TAG_GROUPS)


def test_exit_group_is_gone_from_get_tag_groups(tmp_db):
    """A DB override is returned wholesale, so the rows must be deleted too."""
    assert "exit" not in db.get_tag_config()
    assert not any(g["id"] == "exit" for g in logic.get_tag_groups())


def test_retiring_the_group_leaves_trade_tags_untouched(tmp_db, day_id):
    """Historical trades keep the exit tags they were given."""
    trade_id = db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, 50.0,
                               "10:00", "10:30")
    db.set_trade_tags(trade_id, "exit", ["Fear / Anxious"])

    db.init_db()

    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT tag FROM trade_tags WHERE trade_id = ? AND group_id = 'exit'",
            (trade_id,)).fetchall()
    assert [r["tag"] for r in rows] == ["Fear / Anxious"]


def test_the_deletion_is_one_shot_and_does_not_fight_the_append(tmp_db):
    """4.8.2 appends the exit vocabulary; this removes it. Running init_db
    repeatedly must not oscillate."""
    for _ in range(3):
        db.init_db()
    assert "exit" not in db.get_tag_config()


def test_exit_tag_signals_is_removed():
    assert not hasattr(logic, "exit_tag_signals")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_tag_config.py -v`
Expected: FAIL — the `exit` group is still present and `exit_tag_signals` still exists.

- [ ] **Step 3: Remove the group from the defaults**

In `app_logic.py`, delete the entire `exit` entry from `TAG_GROUPS` (the dict with `"id": "exit"`). Leave `with`, `volume`, `setup` and `pre` untouched.

- [ ] **Step 4: Delete `exit_tag_signals`**

Remove the whole `def exit_tag_signals(...)` function from `app_logic.py`. Task 5 already removed its only call site; confirm with `grep -n exit_tag_signals app_logic.py templates/*.html` that nothing references it.

- [ ] **Step 5: Add the one-shot deletion migration**

In `database.py` `init_db()`, **after** the 4.8.2 exit-vocabulary append block:

```python
        # One-shot: retire the 'exit' tag group. Its vocabulary is superseded by
        # management_issue (what changed), emotion (why) and the target-fit ratio
        # (what price did). get_tag_groups() serves a DB override wholesale, so
        # removing it from TAG_GROUPS is not enough — the rows must go.
        #
        # Runs AFTER the 4.8.2 append and does not clear that migration's flag:
        # on a fresh database the append adds the vocabulary once, this removes
        # it once, and neither runs again. trade_tags is deliberately untouched
        # so historical trades keep the exit tags they were given.
        already = conn.execute(
            "SELECT 1 FROM app_config WHERE key = 'migration_exit_group_retired'"
        ).fetchone()
        if not already:
            conn.execute("DELETE FROM tag_config WHERE group_id = 'exit'")
            conn.execute(
                "INSERT OR REPLACE INTO app_config (key, value) VALUES "
                "('migration_exit_group_retired', '1')"
            )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_tag_config.py -v`
Expected: all pass.

- [ ] **Step 7: Verify against a copy of the real database**

```bash
SC=$(mktemp -d) && cp data/journal.db "$SC/j.db" && python3 - <<PY
import database as db
db.DB_PATH = "$SC/j.db"
import sqlite3
c = sqlite3.connect("$SC/j.db")
before = c.execute("SELECT COUNT(*) FROM trade_tags WHERE group_id='exit'").fetchone()[0]
db.init_db(); db.init_db()
after = c.execute("SELECT COUNT(*) FROM trade_tags WHERE group_id='exit'").fetchone()[0]
print("exit tag_config rows:", c.execute("SELECT COUNT(*) FROM tag_config WHERE group_id='exit'").fetchone()[0])
print("trade_tags exit rows before/after:", before, after)
PY
```

Expected: `tag_config` rows `0`; `trade_tags` count unchanged. **Never run this against `data/journal.db` itself.**

- [ ] **Step 8: Run the full suite and commit**

Run: `python3 -m pytest tests/ -v`

```bash
git add app_logic.py database.py tests/test_tag_config.py
git commit -m "feat: retire the exit tag group

Superseded by management_issue (what changed), emotion (why) and the
target-fit ratio (what price did). get_tag_groups serves a DB override
wholesale, so the tag_config rows are deleted too — one-shot and ordered
after the 4.8.2 append so the two migrations cannot oscillate. trade_tags
is untouched: historical trades keep their exit tags."
```

---

## Task 7: Assessment page

No automated tests — this project has no JS test infrastructure. Follow the manual steps literally.

**Files:**
- Modify: `templates/live_v2.html` (assessment markup ~4900-4934; `commitStrength()`)
- Modify: `server.py` (`/api/trade-strength` accepts `emotion_entry`)
- Modify: `database.py` (`create_trade_strength` accepts `emotion_entry`)

**Interfaces:**
- Consumes: `logic.ENTRY_EMOTIONS` (Task 2), `POST /api/live/<id>/assessment` (Task 2).
- Produces: nothing later tasks consume.

- [ ] **Step 1: Relabel the Patience tile**

At `templates/live_v2.html:4906`, change only the label and helper text. The state variable stays `processPatience` and the DB column stays `patience` — no migration:

```js
      ${checkRow('patience', processPatience, 'Trade came to me', 'I waited for my level.')}
```

- [ ] **Step 2: Make the tile also set the pre-trade tag**

Find the click handler `checkRow` binds to (search `processPatience =` in `live_v2.html`). Where it toggles the value, also toggle the `pre` tag:

```js
  // The tile and the 'Trade came to me' pre-trade tag are the same claim. The
  // TAG is the source of truth — four consumers read it (the weekly came_to_me
  // detector, PRE_GOOD in day.html, and two places in analytics.html) while the
  // patience column feeds only its own 0/3 counter. They can drift if the tag is
  // later edited at review; that is accepted, not synced.
  setPreTag('Trade came to me', processPatience);
```

If no `setPreTag` helper exists, add one beside the other tag helpers that adds or removes a single tag from the `pre` group in the live trade's `tags_json`, then persists via the existing tags endpoint.

- [ ] **Step 3: Replace the CALM/FOMO toggle with the entry emotion picker**

At `live_v2.html:4920-4930`, replace the `STATE` group's contents. Keep the `CONFIDENCE` group untouched:

```html
        <div class="sa-bottom-group">
          <div class="sa-bottom-label">EMOTION</div>
          <div class="ef-toggle-group sa-emotion-group">
            ${['calm','impatience','frustration','greed','overconfidence','distracted']
              .map(e => emotionBtn(e)).join('')}
          </div>
        </div>
```

Add `emotionBtn(e)` beside `mentalBtn`, following its exact pattern — active class when `strengthEmotion === e`, label the value with the first letter capitalised and underscores replaced by spaces.

Six values only. `fear_of_loss` and `fear_of_giving_back` require an open position and are deliberately absent; the server rejects them on this field.

- [ ] **Step 4: Add Setup and Pre-trade pickers to the right panel**

In the assessment page's right panel, add Setup and Pre-trade tag groups rendered exactly like the review page's existing right-panel groups (search `SETUP` in the review panel markup and copy the pattern, including the click handler that writes to `tags_json`).

- [ ] **Step 5: Send the new field on commit**

In `commitStrength()`, replace `mental_state: strengthMental,` with:

```js
      emotion_entry: strengthEmotion,
```

**`emotion_entry` has to reach two places, and this is the part that is easy to get wrong.**

The assessment page runs *before* the live trade exists — it saves to `trade_strength`, which is
keyed by context and account, and the trade is created afterwards carrying a `strength_id`
(`live_trades.strength_id`, `database.py:2091`). But Task 1 put `emotion_entry` on `live_trades` and
`trades`, because that is where the analytics read it. So:

1. Add `emotion_entry TEXT` to `trade_strength` with the same guarded-migration style as Task 1, and
   accept it in `db.create_trade_strength` and `POST /api/trade-strength`.
2. In the `POST /api/live` handler in `server.py`, where the trade is created with `strength_id`,
   read that strength record and copy its `emotion_entry` onto the new live trade:

```python
    # The assessment page runs before the trade exists, so the entry emotion is
    # recorded on trade_strength. Copy it onto the trade now, where the weekly
    # analytics read it — they group by column, not by joining through strength.
    entry_emotion = None
    if body.get("strength_id"):
        strength = db.get_trade_strength(int(body["strength_id"]))
        entry_emotion = (strength or {}).get("emotion_entry")
```

and pass `emotion_entry=entry_emotion` into the `db.create_live_trade(...)` call.

If `db.get_trade_strength(strength_id)` does not exist, add it — a single-row `SELECT * FROM
trade_strength WHERE id = ?` returning a dict or `None`.

Update `SCHEMA.md` for the new `trade_strength` column and note the copy-on-create.

`mental_state` stays in the schema, no longer written. Historical rows keep it.

- [ ] **Step 6: Manual verification**

Run `python3 server.py` and open the Trade V2 page.

1. The first tile reads **Trade came to me** with helper text *I waited for my level.* — the tile's visual treatment is unchanged.
2. The counter still reads `0 / 3 process · 0 / 4 technical` and moves when tiles are ticked.
3. The MENTAL STATE row now offers six emotions; there is no CALM/FOMO pair and no fear option.
4. CONFIDENCE is unchanged.
5. Setup and Pre-trade pickers appear in the right panel and persist a selection.
6. Tick **Trade came to me**, then check the pre-trade panel — the *Trade came to me* tag is now selected. Untick the tile; the tag clears.
7. Press ASSESS & CONTINUE, then confirm storage:

```bash
python3 -c "
import database as db
with db.get_conn() as c:
    r = c.execute('SELECT patience, emotion_entry FROM trade_strength ORDER BY id DESC LIMIT 1').fetchone()
    print(dict(r))"
```

Expected: `patience` 1, `emotion_entry` the value you picked.

- [ ] **Step 7: Commit**

```bash
git add templates/live_v2.html server.py database.py SCHEMA.md
git commit -m "feat: assessment page — relabelled tile, entry emotion, setup/pre-trade

The Patience tile becomes 'Trade came to me' and also sets the pre-trade tag
of that name, so the four existing consumers of that tag keep working. The tag
is the source of truth; the patience column feeds only its own counter.
CALM/FOMO is replaced by six entry emotions — the two fear states need an open
position and are offered only at review."
```

---

## Task 8: Review page

No automated tests. Follow the manual steps literally.

**Files:**
- Modify: `templates/live_v2.html` (`renderReviewCenter` ~5072; score hero ~5166; the two question blocks ~5194 and ~5206)

**Interfaces:**
- Consumes: `POST /api/live/<id>/assessment` and `POST /api/trade/<id>/assessment` (Task 2).
- Produces: nothing later tasks consume.

- [ ] **Step 1: Delete the superseded blocks**

In `renderReviewCenter`, remove:
- the `EXECUTION SCORE · PROCESS ONLY` hero and its three sub-counters (~5160-5190)
- `1 OF 2 · MANAGEMENT` — *How were you during the trade?* with its four cards (~5194)
- `2 OF 2 · EXIT DISCIPLINE` — *How did you exit?* with its cards (~5206)

Keep the `ENTRY RECAP — RECORDED AT ENTRY · NOT EDITABLE` block and everything below it.

- [ ] **Step 2: Add the grade control**

In their place, first:

```html
        <div class="rv2-section">
          <div class="rv2-q-title">Which game did you play?</div>
          <div class="rv2-q-sub">P&amp;L has no vote — a losing trade can be A-game, and a winner can be C-game.</div>
          <div class="rv2-grade-row">
            ${gradeBtn('A', 'A-game', 'The opportunity came to you; you entered intentionally; risk and size were appropriate; management decisions were justified by your process and the information available at the time. A technical read can still turn out to be wrong.')}
            ${gradeBtn('B', 'B-game', 'The core process remained recognisable, but there was minor emotional or execution leakage — entering somewhat early, hesitation, overmanagement, or an emotion-driven early exit.')}
            ${gradeBtn('C', 'C-game', 'A meaningful breakdown: forced trade, chase/FOMO entry, revenge trading, inappropriate risk, moving a stop because you could not accept the loss, major overtrading, or another obvious abandonment of your process.')}
          </div>
        </div>
```

`gradeBtn(value, title, description)` follows the existing card pattern used by the deleted management cards — a title line and a description line, with an active class when selected.

- [ ] **Step 3: Add the management chain**

Below the grade:

```html
        <div class="rv2-section">
          <div class="rv2-q-title">How did you manage it?</div>
          <div class="rv2-q-sub">Everything after entry until flat, including the exit.</div>
          <div class="rv2-q-row">
            ${mgmtBtn('followed', 'Followed process')}
            ${mgmtBtn('deviated', 'Deviated')}
          </div>
        </div>

        ${reviewMgmt === 'deviated' ? `
        <div class="rv2-section">
          <div class="rv2-q-title">What changed?</div>
          <div class="rv2-chip-row">
            ${['early_exit','late_exit','stop_change','overmanaged','under_managed','premature_scale_out']
              .map(v => chipBtn('management_issue', v)).join('')}
          </div>
          <div class="rv2-q-sub">Early exit means premature or unjustified relative to your process — not merely that price continued after you got out.</div>
        </div>` : ''}

        <div class="rv2-section">
          <div class="rv2-q-title">What were you feeling?</div>
          <div class="rv2-chip-row">
            ${['calm','fear_of_loss','fear_of_giving_back','greed','frustration','impatience','overconfidence','distracted']
              .map(v => chipBtn('emotion', v)).join('')}
          </div>
        </div>

        ${(reviewGrade === 'B' || reviewGrade === 'C') ? `
        <div class="rv2-section">
          <div class="rv2-q-title">Did you break a rule?</div>
          <div class="rv2-chip-row">
            ${['none','traded_outside_plan','exceeded_risk','revenge_trade','overtraded']
              .map(v => chipBtn('process_violation', v)).join('')}
          </div>
        </div>` : ''}
```

`chipBtn(field, value)` renders one selectable chip, labelling the value with underscores replaced by spaces and the first letter capitalised, active when the current value matches.

The management-issue block appears only on `deviated`, and the violation block only on B or C. These mirror rules the server also enforces, so a stale tab cannot post a contradiction.

- [ ] **Step 4: Wire the saves**

Each control posts the single field it owns to `POST /api/live/<id>/assessment`, then re-renders. Follow the pattern of `dynEditTrancheTarget` — `fetch`, check `res.ok`, `showToast` the error, then `refreshTradeFromServer`.

When the grade changes from B/C to A, clear `process_violation` in the same post (send `null`), so a violation cannot be stranded on a trade now graded A — which the server would reject on the next write.

- [ ] **Step 5: Set `pre_tags_late`**

When the right panel's Pre-trade group is edited on the review screen **and the trade had no pre-trade tags at entry**, include `pre_tags_late: 1` in the assessment post. Determine "had none at entry" from the tags present when the review screen first rendered, captured once on render — not on every keystroke.

- [ ] **Step 6: Manual verification**

Run `python3 server.py`, open a closed trade, go to REVIEW.

1. The `n/5` execution score hero is gone, as are both old question blocks.
2. Three grade cards appear with the full definitions and the "P&L has no vote" line.
3. Choosing **Followed process** shows no *What changed?* block; choosing **Deviated** reveals it.
4. Choosing grade **A** shows no *Did you break a rule?* block; **B** or **C** reveals it.
5. Set grade B + a violation, then change the grade to A — the violation block disappears and the stored value clears rather than erroring.
6. The entry recap, notes fields and the right panel (Technicals, Volume, Setup, Pre-trade) are unchanged.
7. Confirm storage:

```bash
python3 -c "
import database as db
lt = db.get_live_trade(<LIVE_ID>)
print({k: lt.get(k) for k in ('grade','management','management_issue','emotion','process_violation','pre_tags_late')})"
```

8. Confirm the server rejects a contradiction a stale tab could send:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST -H 'Content-Type: application/json' \
  -d '{"grade":"A","process_violation":"revenge_trade"}' \
  http://127.0.0.1:5050/api/live/<LIVE_ID>/assessment
```

Expected: `400`.

- [ ] **Step 7: Commit**

```bash
git add templates/live_v2.html
git commit -m "feat: review page — A/B/C grade replaces the 5-point score

The exit is no longer scored separately: it is the final management decision,
so the two old question blocks collapse into one management chain. Management
issue appears only on 'deviated' and the violation field only on B or C, so an
A-game trade stays two clicks."
```

---

## Task 9: Weekly page

No automated tests for the template; the payload behind it is covered by Task 5.

**Files:**
- Modify: `templates/weekly_review.html`

**Interfaces:**
- Consumes: the summary keys from Task 5 — `grades`, `graded_of`, `target_fit_dist`, `bc_diagnosis`, and the row keys `grade`, `capture_band`, `pnl`.

- [ ] **Step 1: Replace the Avg Exec Score tile with the grade distribution**

In the Behaviour grid, replace the `Avg Exec Score` card with three cards plus a coverage line:

```html
      {% set s = data.plan_execution.summary %}
      {% for g in ['A', 'B', 'C'] %}
      <div class="wr-beh-card">
        <div class="lbl">{{ g }}-game</div>
        <div class="val {{ 'pos' if s.grades[g].net >= 0 else 'neg' }}">{{ money(s.grades[g].net) }}</div>
        <div class="sub">{{ s.grades[g].count }} trades</div>
      </div>
      {% endfor %}
```

and immediately below the grid:

```html
      <div class="wr-pe-coverage">Graded {{ s.graded_of }} of {{ data.plan_execution.rows|length }} trades.</div>
```

- [ ] **Step 2: Add the capture colour styles**

Beside the existing `.wr-pe-*` rules:

```css
.wr-cap-red    { color: #c0392b; }
.wr-cap-orange { color: #ffb347; }
.wr-cap-green  { color: var(--green); }
.wr-cap-blue   { color: #4aa3f0; }
```

- [ ] **Step 3: Rework the table**

In the header row, remove `<th>Verdict</th>` and add `<th class="num">P&amp;L</th>` after `Capture`. In the body row, remove the verdict `<td>` and change the capture cell to:

```html
          <td class="num">{% if r.capture_band %}<span class="wr-cap-{{ r.capture_band }}">{{ '{:.2f}'.format(r.capture) }}</span>{% else %}—{% endif %}</td>
          <td class="num {{ 'pos' if r.pnl >= 0 else 'neg' }}">{{ money(r.pnl) }}</td>
```

A blank capture means the trade lost — the P&L column beside it says so, which is why the two go together.

Add a `Grade` cell after `Setup`:

```html
          <td>{% if r.grade %}<span class="wr-pe-v">{{ r.grade }}</span>{% else %}—{% endif %}</td>
```

Update the free-text row's `colspan` to match the new column count, and drop the `tag_conflict` / `tag_suggestion` spans and the `r.exit_tag` references from it — those keys no longer exist. The `out:` prefix now shows `notes_exit` alone.

- [ ] **Step 4: Add the target-fit distribution and the B/C diagnosis**

Above the table, after the coverage line:

```html
      {% if s.target_fit_dist.of %}
      <div class="wr-pe-headline">
        Targets: {{ s.target_fit_dist.too_far }} too far ·
        {{ s.target_fit_dist.calibrated }} well calibrated ·
        {{ s.target_fit_dist.too_close }} too close
        <span class="realism">across {{ s.target_fit_dist.of }} trades with a peak and a target.</span>
      </div>
      {% endif %}

      {% if s.bc_diagnosis.of %}
      <div class="wr-pe-headline">
        Across {{ s.bc_diagnosis.of }} B/C trade{{ 's' if s.bc_diagnosis.of != 1 }}:
        {% if s.bc_diagnosis.top_issue %}most common issue
        <span class="fear">{{ s.bc_diagnosis.top_issue[0].replace('_', ' ') }}</span>
        ({{ s.bc_diagnosis.top_issue[1] }}){% endif %}{% if s.bc_diagnosis.top_issue and s.bc_diagnosis.top_emotion %};
        {% endif %}{% if s.bc_diagnosis.top_emotion %}most common emotion
        <span class="fear">{{ s.bc_diagnosis.top_emotion[0].replace('_', ' ') }}</span>
        ({{ s.bc_diagnosis.top_emotion[1] }}){% endif %}.
      </div>
      {% endif %}
```

- [ ] **Step 5: Delete the fear/greed headline**

Remove the whole `wr-pe-headline` block that renders `s.fear`, `s.greed` and `s.realism`. Those keys no longer exist and the block would raise. It judged an exit from price data alone, which is the thing this redesign removes.

Also remove the verdict-tile band (the `froze_at_target` / `bailed_early` / `market_didnt_pay` loop). Keep the give-back and missed-run tiles and the peak coverage line.

- [ ] **Step 6: Manual verification**

Run `python3 server.py`, open `/weekly-review`.

1. Three grade cards replace Avg Exec Score, with `Graded N of M trades` beneath.
2. The table shows `Grade`, a coloured `Capture`, and `P&L`; there is no `Verdict` column.
3. A losing trade shows `—` for Capture and a red P&L.
4. Capture colours match the bands: below 0.60 red, 0.60–0.80 orange, 0.80–1.10 green, above 1.10 blue.
5. The targets line appears when at least one trade has both a peak and a target.
6. The B/C diagnosis line appears only when the week has a B or C trade.
7. No fear/greed headline and no verdict tiles anywhere.
8. A week with no graded trades renders without error and shows zeros only in the grade cards, not a stray diagnosis line.
9. A **pre-feature** week (no grades, no peaks, no targets) renders without raising.

- [ ] **Step 7: Commit**

```bash
git add templates/weekly_review.html
git commit -m "feat: weekly page — grade distribution, coloured capture, target fit

Replaces the average execution score with an A/B/C distribution, adds the P&L
the table never showed, colours capture by band, and reports target fit as a
weekly distribution rather than per row — one row of it is hindsight, twenty
is calibration. The fear/greed headline is deleted: it accused from price
data alone."
```

---

## Task 10: Day page

**Files:**
- Modify: `app_logic.py` (`compute_combined_day_score`)
- Modify: `templates/day.html` (trade trays)
- Test: `tests/test_grade_analytics.py`

**Interfaces:**
- Consumes: the `grade` column (Task 1).
- Produces: nothing later tasks consume.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_grade_analytics.py`:

```python
def test_day_score_no_longer_uses_the_execution_score(tmp_db, day_id):
    """The 5-point score is retired; the day grade reflects the day process
    checklist alone."""
    import json as _json
    db.insert_trade(day_id, 1, "Long", 1, 7700.0, 7710.0, 50.0, "10:00", "10:30",
                    execution_score_json=_json.dumps({"version": 1, "score": 1}))
    trades = db.get_trades_for_day(day_id)

    with_exec = logic.compute_combined_day_score('{"a": true, "b": true}', trades)
    without = logic.compute_combined_day_score('{"a": true, "b": true}', [])

    assert with_exec == without, "trade execution scores must not move the day grade"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_grade_analytics.py -k day_score -v`
Expected: FAIL — the two values differ because the legacy branch folds `exec_score` in.

- [ ] **Step 3: Drop the execution component**

In `compute_combined_day_score`, remove the v2 branch and the legacy `exec_pct` accumulation, returning the day-process percentage alone:

```python
def compute_combined_day_score(day_score_json, trades=None):
    """Day grade from the day's own process checklist.

    The per-trade execution score it used to fold in was retired along with the
    5-point scoring; trade quality is now the A/B/C grade, which is a judgement
    rather than a percentage and does not average into a day score. `trades` is
    kept in the signature so existing callers need no change.
    """
    day_result = compute_day_score(day_score_json)
    if day_result is None:
        return None
    checked, total = day_result
    return round(checked / total * 100) if total else None
```

Then delete `get_execution_score_version` and `get_trade_execution_score` if nothing else calls them — check with `grep -rn "get_execution_score_version\|get_trade_execution_score" .`

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 -m pytest tests/test_grade_analytics.py -k day_score -v`
Expected: PASS.

- [ ] **Step 5: Show the grade on the trade trays**

In `templates/day.html`, in the trade tray header beside the direction and P&L, add:

```html
{% if trade.grade %}<span class="tray-grade tray-grade-{{ trade.grade }}">{{ trade.grade }}</span>{% endif %}
```

with styles beside the existing tray rules:

```css
.tray-grade { font-size:10px; font-weight:600; padding:1px 6px; border-radius:3px; border:0.5px solid var(--border2); }
.tray-grade-A { color: var(--green); border-color: var(--green); }
.tray-grade-B { color: #ffb347; border-color: #ffb347; }
.tray-grade-C { color: #ff6b6b; border-color: #ff6b6b; }
```

- [ ] **Step 6: Manual verification**

1. Open a day with a graded trade — the letter appears on the tray, coloured.
2. An ungraded trade shows no chip, not an empty one.
3. The day grade percentage still renders and no longer moves when a trade's old execution score differs.

- [ ] **Step 7: Bump the version and changelog**

Set `VERSION` to `4.9.0`, and prepend to `CHANGELOG.md`:

```markdown
## [4.9.0] — 2026-09-07

### Changed

- **The 5-point execution score is replaced by one A/B/C grade per trade**, chosen by the trader,
  with the framework's definitions on screen. P&L has no vote: a losing trade can be A-game and a
  winner can be C-game. The weekly page shows a grade distribution instead of an average, because
  averaging letters recreates the number this replaced.
- **The exit is no longer scored separately.** It is the final management decision, so the review
  page's two question blocks collapse into one chain: grade → management → management issue (only
  when deviated) → emotion → process violation (only on B or C).
- **Five diagnostic fields** recorded per trade: management, management issue, emotion, entry
  emotion and process violation — as columns, so "what turns my A-game into B-game" is one query.
- **The peak-derived verdicts are gone** (froze at target / bailed early / market didn't pay), along
  with the fear and greed headlines. They judged an exit from price data alone; the framework is
  explicit that an early exit is only a mistake if unjustified by process.
- **Target fit** joins capture: peak over target, reported as a weekly distribution (too far / well
  calibrated / too close). Capture asks whether you waited for your plan; target fit asks whether the
  plan was reasonable. Capture is now coloured by band and blank on a loss.
- **The weekly table shows P&L**, which it never did — the figure beside size was the risk.
- **The exit tag group is retired**, superseded by management issue, emotion and target fit.
  Historical trades keep their exit tags.
- The assessment page's Patience tile is now **Trade came to me** and sets the pre-trade tag of that
  name; CALM/FOMO is replaced by six entry emotions.
```

- [ ] **Step 8: Run the full suite and commit**

Run: `python3 -m pytest tests/ -v`

```bash
git add app_logic.py templates/day.html CHANGELOG.md VERSION tests/
git commit -m "feat: day grade drops the execution component; trays show the letter

Bumps version to 4.9.0."
```

---

## Verification checklist

Run after the final task. Every item must pass.

- [ ] `python3 -m pytest tests/ -v` — all pass
- [ ] `python3 -c "import database as db; db.init_db(); db.init_db(); print('ok')"` — migrations re-run cleanly against the **real** database
- [ ] Exit tags survive: `python3 -c "import sqlite3;c=sqlite3.connect('data/journal.db');print(c.execute(\"SELECT COUNT(*) FROM trade_tags WHERE group_id='exit'\").fetchone()[0])"` — non-zero, unchanged from before the upgrade
- [ ] `python3 -c "import database as db; print('exit' in db.get_tag_config())"` — `False`
- [ ] Open a pre-feature trade in the day view — renders with no grade chip and no error
- [ ] Weekly review for a week predating the feature — renders with zero grade cards and no diagnosis line
- [ ] `grep -rn "exit_tag_signals\|classify_verdict\|verdicts_of\|market_didnt_pay" app_logic.py templates/` — no hits
