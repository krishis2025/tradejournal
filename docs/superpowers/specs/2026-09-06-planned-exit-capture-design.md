# Planned exit capture & weekly Plan-vs-Execution review

**Date:** 2026-09-06
**Status:** Approved design, ready for implementation planning
**Version target:** 4.8.0

## Goal

Capture the **planned exit (target)** for each entry decision, alongside the intended stop
already captured, so the weekly review can compare *planned stop → planned exit → actual exit*
and surface whether exits are being taken out of fear or greed.

Everything else the review needs is already recorded. This spec adds one field and one
report section.

## What already exists (do not rebuild)

| Review column | Existing source |
|---|---|
| Setup | `trade_tags`, `group_id='setup'` |
| Level traded | `trade_tags`, `group_id='with'` (Value, VWAP, ADH, AVWAP) |
| Reason for entering | `trades.notes` |
| Reason for exiting | `trades.notes_exit` |
| Position size & why | `trades.qty` + risk derived from `fills.stop_price` |
| Planned / Unplanned | `trade_tags`, `group_id='exit'` |
| Emotion | `live_trades.guard_json.mental_state` + `pre` tag group |
| Actual exit | `trades.avg_exit` |
| **Planned exit** | **missing — this spec** |

The weekly page already renders a Setup performance table and a Trade ledger
(`Date | Dir | Qty | P&L | Read | Setup`). Both stay as they are.

## Design principle

The fear/greed read is only honest if the planned exit is recorded **before the outcome is
known**. A freely editable target drifts toward what actually happened and makes the whole
report self-confirming. Every decision below follows from that.

---

## 1. Data model

Two nullable columns on **both** ledger tables, mirroring `stop_price`/`stop_source`, added
with the existing guarded `ALTER TABLE` pattern in `init_db()` (`database.py:302-315`):

- `live_trade_executions`: `target_price REAL` (nullable), `target_source TEXT NOT NULL DEFAULT 'none'`
- `fills`: `target_price REAL` (nullable), `target_source TEXT NOT NULL DEFAULT 'none'`

`target_source` values:

- `'none'` — no target recorded (the honest NULL)
- `'entered'` — typed on the Entry or Add form
- `'edited'` — corrected in the Manage ledger before any exit fill

The default differs deliberately from `stop_source`. A defaulted stop (`'default'`, auto 20-pt)
still represents real risk; a missing target means **no plan existed**, which is itself a finding.
There is no auto-defaulted target.

Signature changes, all keyword-defaulted so existing callers keep working:

- `insert_fill(trade_id, fill_time, side, qty, price, exit_type=None, stop_price=None, stop_source='default', target_price=None, target_source='none')`
- `add_live_trade_execution(live_trade_id, exec_type, portion, qty, price, exec_time, pnl, stop_price=None, stop_source='default', target_price=None, target_source='none')`
- New `update_live_trade_execution_target(exec_id, target_price, target_source='edited')` — mirrors
  `update_live_trade_execution_stop` (`database.py:1975`); touches only the two target columns.

**Not touched:** `live_trade_levels` (working stop/TP pool) and `live_trades.initial_risk`.
A planned exit is a record of intent, not a live level. Storing it as a TP row would let
trailing behavior mutate the plan — exactly what the freeze rule prevents.

Nothing derived is persisted: no stored R:R, no stored capture %.

`SCHEMA.md` updated for both tables (project rule). `CHANGELOG.md` and `VERSION` bumped.

---

## 2. Capture UI

### Entry form (`live_v2.html`, `ef-` fields)

- New `TARGET` input directly under `STOP`. Same styling, `step="0.25"`, no default value.
- The `RISK $398` readout becomes `RISK $398 · 1.9R`. The R multiple renders only when both
  stop and target are present, and disappears when target is blank.
- `handleEnterClick` (`live_v2.html:8151`) reads `ef-target` the way it reads `ef-stop`:
  omitted from the request body when empty.

### Add form (`live_v2.html`, `dyn-add-` fields)

- New `dyn-add-target` input beside `dyn-add-stop`, same optional treatment.
- Every OPEN and ADD is prompted for its own target. Blank is acceptable, so a fast add
  costs no extra keystrokes.

### Manage ledger (`buildTransactionFeed`, `live_v2.html:7163`)

- One new `Target` column between `Stop` and `Risk`, so the two plan cells sit together and
  the derived Risk stays adjacent to P&L.
- Markers reuse the existing stop language:
  - `entered` / `edited` → mint check
  - `none` → amber dot, title "no planned exit recorded"
  - EXIT rows → inert dash, same as their Stop cell
- **No per-row R:R column.** The ledger is already 8 columns; reward and R:R go in the footer:
  `IDEA RISK $398 · TARGET $760 · 1.9R`, plus an amber `N entr(ies) with no planned exit`
  note mirroring the existing `N stops on 20-pt default` note.
- **No tap-to-pull chip on the target cell.** Working stops are a legitimate source for
  "what am I risking"; working TPs are not a legitimate source for "what did I plan",
  because they move mid-trade.

### The freeze

- A target cell is editable only while the trade has **no exit-side execution**, where
  exit-side means `exec_type` in `EXIT`, `STOP_HIT`, `TP_HIT`, `MANUAL_EXIT` (the same set
  `buildTransactionFeed` already treats as non-entry rows).
- Once any exit exists, the cell renders as static text with a lock glyph,
  title "locked at first exit".
- **Enforced server-side, not only in the UI** (see §3). A UI-only lock is decorative.

---

## 3. Routes (`server.py`)

- `POST /api/live` — read optional `target_price`; present → store on the OPEN execution with
  `target_source='entered'`; absent → NULL / `'none'`. Mirrors the stop branch at `server.py:1015`.
- `POST /api/live/<id>/add` — same, on the ADD execution. Mirrors `server.py:1218`.
- **New** `PATCH /api/live/<int:live_id>/execution/<int:exec_id>/target`
  - Body `{ "target_price": <float> }` → `update_live_trade_execution_target(exec_id, price, 'edited')`
  - **Returns `409` if the trade already has any exit-side execution.** This is the freeze.
  - Routes only; no SQL or math in the handler (three-layer rule).

---

## 4. Carry-through to journal

In `app_logic.close_live_trade_to_journal` (`app_logic.py:1095`), extend the existing
`insert_fill` calls that already carry `stop_price`/`stop_source`:

- Entry-side execs (`app_logic.py:1208`): pass `target_price=e.get("target_price")` and
  `target_source=e.get("target_source") or 'none'`.
- Legacy synthesized entry fill (`app_logic.py:1221`): `target_price=None, target_source='none'`.
- Exit-side fills (`app_logic.py:1225`): `target_price=None, target_source='none'`.

---

## 5. Derivation

All derived on read; nothing stored.

```
sign    = +1 for long, -1 for short
E       = trades.avg_entry
A       = trades.avg_exit
T       = sum(qty_i * target_i) / sum(qty_i)   over entry fills where target_i IS NOT NULL
S       = sum(qty_i * stop_i)   / sum(qty_i)   over entry fills where stop_i   IS NOT NULL
capture = sign*(A - E) / (sign*(T - E))
```

Rules:

- Weighting spans only rows that **have** a target. A trade that targeted the core but not the
  add still yields an honest number and carries a `partial plan` marker.
- A trade with no target on any entry row is **excluded from bucket math** and counted
  separately as `No plan · N`.
- Guard the denominator: if `|T - E| < 0.25` (one MES/ES tick), treat the trade as `No plan`
  rather than emitting a divide-by-zero or an absurd capture value. A target within one tick
  of the entry is not a plan.
- `S` is not used in the capture formula. It feeds the `Stop` column and the `Size/Risk`
  column of the weekly table (§7), so the planned stop, planned exit and actual exit can be
  read on one line.
- `$/point` comes from `execution_json.instrument`, the same path the existing tranche-risk
  derivation uses (`compute_tranche_risk`, `app_logic.py:687`).

Buckets, with the tolerance band read from `app_config` key `plan_capture_band`
(default `0.10`, tunable without a code change):

Let `b = plan_capture_band` (default `0.10`). Boundaries are explicit so the edges cannot
be implemented two ways:

| condition | bucket |
|---|---|
| `capture <= 0` | Stopped / Loss |
| `0 < capture < 1 - b` | Cut Early |
| `1 - b <= capture <= 1 + b` | At Plan |
| `capture > 1 + b` | Ran Past |

At the default band that reads: `<= 0`, `0 to 0.90` exclusive, `0.90 to 1.10` inclusive
on both ends, `> 1.10`.

### Data plumbing

`get_trades_in_range` (`database.py:2703`) returns trades plus tags, but no fills.
Add **one** new function rather than an N+1:

- `db.get_entry_fills_for_trades(trade_ids)` — single `IN`-clause query returning entry-side
  fills (`qty`, `price`, `stop_price`, `stop_source`, `target_price`, `target_source`)
  keyed by trade id.

Weighting and bucketing live in `app_logic`; the query lives in `database.py` (three-layer rule).

### Known limitation — state it in the UI

The journal has no price feed. Capture % compares planned exit to actual exit, so it
**cannot** distinguish:

- price reached the target, it wasn't taken, then it was given back → capture 0.6
- price never approached the target and what was there was taken → capture 0.6

Both read as `Cut Early`. Without max-favorable-excursion data, no formula resolves this.

**Mitigation:** the exit tag supplies what the price data cannot. `Fear / Anxious` at capture
0.6 is a fear exit; `Target never reached` at capture 0.6 is a correct read of a market that
did not pay. The weekly roll-up therefore crosses **bucket x exit tag**, and the fear/greed
headline is drawn from that crossing — never from capture % alone.

---

## 6. Exit tag vocabulary

The `exit` tag group (`app_logic.TAG_GROUPS`) currently has two values:
`Planned — Monitored Continuation`, `Fear / Anxious`. Seed additional defaults so the exit
reason becomes a countable dimension that can be crossed with capture %:

- `Target hit`
- `Target never reached`
- `Stopped out`
- `Greed / chased`
- `Time stop`
- `Management error`

The group stays `multi: False`. Tag config is already user-editable in Settings, so the list
can be tuned afterward without code changes. Existing tagged trades are untouched.

---

## 7. Weekly page (`weekly_review.html`)

New `PLAN vs EXECUTION` section. The existing Trade ledger and Setup performance table stay
exactly as they are.

**Roll-up strip** (top): four bucket tiles — count, net $, avg capture % each — plus the
`No plan · N` count, plus the fear/greed headline.

The headline is computed from the bucket x exit-tag crossing, not from capture % alone:

- **Fear signal** = trades in `Cut Early` tagged `Fear / Anxious`. Reported as
  count, net $, and avg capture: *"3 trades cut at an average 58% of plan while tagged
  fear — $412 of planned move left on the table."*
- **Greed signal** = trades tagged `Greed / chased` in any bucket, plus `Ran Past` trades
  that ended net negative (held beyond plan and gave it back).
- **Neutral** = `Cut Early` tagged `Target never reached`. Explicitly excluded from the
  fear count — this is the market not paying, not a discipline break.

When a bucket has no trades, its clause is omitted rather than rendered as a zero.

**Table**: twelve columns will not fit, so each trade renders as **two rows** — numbers on top,
free text beneath:

```
Date  Setup            Level  Stop     Plan     Actual   Capture  Size/Risk  Exit tag      Emotion
Jul 8 Recapture VWAP   VWAP   7688.50  7760.00  7731.25  0.60     3 · $398   Fear/Anxious  eager
      in: strong buying volume after reclaim · out: pulled it when it stalled at the half-back
```

Column sources: `Level` from the `with` tag group; `Emotion` from `guard_json.mental_state`
plus `pre` tags; `in:` from `trades.notes`; `out:` from `trades.notes_exit`, verbatim.

Reads journal trades only, consistent with the rest of the weekly page. An open live trade
appears after it is pushed.

---

## 8. Out of scope

- **No new trajectory detector** for cut-early. It would fit `DETECTOR_REGISTRY` naturally and
  give a cross-week trend, but it changes `insight_log` semantics and needs a backfill run.
  Revisit once several weeks of target data exist to calibrate the band against.
- No editing of targets on the journal side after push. The columns support it; this spec
  keeps the change to the live/Manage flow and the weekly read.
- No change to working stop/TP behavior, the right-panel net-risk math, or `initial_risk`.
- No max-favorable-excursion capture (would require a price feed).

---

## 9. Testing

- Migration is re-runnable: `init_db()` twice leaves one copy of each column.
- Entry with a target stores `'entered'`; entry without stores NULL / `'none'`.
- Add with and without a target, on the same trade, produces the `partial plan` marker.
- Ledger target edit before any exit succeeds and sets `'edited'`.
- Ledger target edit after an exit returns `409` and leaves the stored value unchanged.
- Push to journal carries `target_price`/`target_source` onto entry-side fills only.
- Capture %: long and short; single entry; multi-entry weighted; partial-plan weighting
  ignores NULL-target rows; `|T - E|` below epsilon falls into `No plan`.
- Bucket boundaries at exactly 0, 0.90 and 1.10 with the default band.
- Weekly page with zero targeted trades in the week renders the section without dividing by zero.
