# Planned exit capture & weekly Plan-vs-Execution review

**Date:** 2026-09-06
**Status:** Approved design, ready for implementation planning
**Version target:** 4.8.0

## Goal

Capture the **planned exit (target)** for each entry decision, alongside the intended stop
already captured, so the weekly review can compare *planned stop → planned exit → actual exit*
and surface whether exits are being taken out of fear or greed.

It also captures the **peak price the market offered** around each trade, recorded after the
fact, which is what lets the review tell "I froze at my target" apart from "the market never
paid" — a distinction the plan-vs-actual comparison cannot make on its own (see §6).

Everything else the review needs is already recorded.

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
| **Planned exit** | **missing — §1-§5 of this spec** |
| **Peak price offered** | **missing — §6 of this spec** |

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

### Known limitation of capture % alone — resolved by §6

The journal has no price feed, so capture % on its own compares planned exit to actual exit
and **cannot** distinguish:

- price reached the target, it wasn't taken, then it was given back → capture 0.6
- price never approached the target and what was there was taken → capture 0.6

Both read as `Cut Early`, and they call for opposite corrections. No formula over the stored
entry/exit prices resolves this — the missing information is simply not in the data.

**This is what §6 exists to fix.** The manually recorded peak price supplies the missing fact,
and §6.4 gives the three-way split that replaces the ambiguous `Cut Early` verdict.

For trades with **no peak recorded**, capture % and its four buckets still render exactly as
specified above — the bucket is never wrong, merely coarse. The exit tag (§7) provides weaker
corroboration in that case. Coverage is always reported (§6.6).

---

## 6. Peak price capture (MFE)

Records the best price the market offered around each trade, entered by hand after the fact.
This is the fact that resolves §5's limitation.

**Journal-side only.** Because capture happens after the push, this section touches `trades`
and nothing in the live flow — no columns on `live_trades`, no change to the Entry, Manage or
Exit tabs, no interaction with the target freeze rule (§2).

### 6.1 Data model

Three columns on `trades`, added with the same guarded `ALTER TABLE` pattern:

- `mfe_price REAL` (nullable) — the peak price observed
- `mfe_timing TEXT` (nullable) — `'during'` (peak came before the exit) | `'after'` (peak came
  after the exit)
- `mfe_window_minutes INTEGER` (nullable) — the window actually used, stamped at write time

**No `mfe_source` column, deliberately.** `stop_price`/`target_price` need a source column
because a defaulted stop is non-NULL but was never intended. There is no default peak, so
`mfe_price IS NULL` already means "not observed". A source column would be redundant state.

### 6.2 The window

Look from the entry through **exit + `mfe_window_minutes`**. Default **30 minutes**, held in
`app_config` key `mfe_window_minutes`.

30 rather than 60 because a 60-minute window on a short intraday trade measures a different
trade than the one that was taken. The window used is stored **per observation**, so retuning
the config later leaves existing rows interpretable instead of silently changing their meaning.

### 6.3 Capture surface — the backfill strip

A `PLAN CHECK` strip on `day.html`, the page already open at session end. It lists **all closed
trades** — winners and losers — that have no `mfe_price` yet, one row each:

`trade # · direction · entry · exit · target · [ peak price input ] · [ before | after my exit ]`

Header reads `PLAN CHECK · N trades missing peak`. Unfilled trades from **earlier days** are
surfaced too (a small "N from earlier days" affordance), so a skipped day does not vanish.

Losers are included on purpose: on a stopped-out trade the peak reveals "I was up $200 before
it stopped me", a give-back leak that is entirely invisible in P&L.

**Push behaviour is unchanged.** Trades reach the journal immediately, exactly as today. The
strip never blocks anything.

**No freeze on these fields**, an intentional asymmetry with the target rule (§2). A target is
a record of intent, so editing it after the outcome corrupts it. A peak is a checkable fact
about the market — a wrong value is simply wrong and should be fixable.

### 6.4 Route

- **New** `POST /api/trade/<int:trade_id>/mfe`, body `{ "mfe_price": <float>, "mfe_timing": "during"|"after" }`
  - Server stamps `mfe_window_minutes` from `app_config` at write time; the client never sends it.
  - Rejects `mfe_timing` outside `during`/`after` with `400`.
  - Calls new `db.set_trade_mfe(trade_id, price, timing, window_minutes)`.
  - Follows the shape of `POST /api/trade/<id>/notes` (`server.py:479`). Routes only, no math.

### 6.5 Derivation

With `P` = `mfe_price`, `T` = weighted target (§5), `A` = `avg_exit`, `E` = `avg_entry`,
`sign` = +1 long / -1 short:

**Three-way split of `Cut Early`** — replaces the ambiguous verdict wherever `P` exists:

| condition | verdict |
|---|---|
| `sign*(P - T) >= 0` and `mfe_timing = 'during'` | **Froze at target** — it was there and was not taken |
| `sign*(P - T) >= 0` and `mfe_timing = 'after'` | **Bailed early** — exited just before it worked |
| `sign*(P - T) < 0` | **Market didn't pay** — not a discipline break |

`Stopped / Loss`, `At Plan` and `Ran Past` keep their §5 definitions.

**Excursion, on every trade** — `sign*(P - A)`, named by the timing flag:

- `during` → **give-back**: open profit returned before exiting
- `after` → **missed run**: distance travelled without you

Dollar value uses `$/point` from `execution_json.instrument`, the same path as §5.

**Target realism** — across the week, the share of covered trades where the target was ever
offered (`sign*(P - T) >= 0`). A low value means targets are set too far out, which looks
identical to fear in capture % but has the opposite fix. Reported alongside the fear/greed
headline, never folded into it.

All three are derived on read. Nothing computed is stored.

### 6.6 Coverage must be reported

Percentages computed over a self-selected subset will overstate whatever prompted the filling.
The weekly section therefore always states `peak recorded on 14 of 19 trades`, and every
peak-derived percentage is computed **over the covered set only**, never over all trades.

Trades without a peak are not excluded from the report — they keep their §5 bucket and simply
carry no verdict, no excursion, and no contribution to target realism.

### 6.7 Known bias

The peak is entered after the outcome is known, so there is a quiet pull toward lowballing it
to make an exit look better. It is far weaker than the corresponding pull on an editable
target — a peak is a checkable fact, not a memory of intent — and it is verifiable against a
chart at any time. Documented so it is known; no mechanism is built against it.

---

## 7. Exit tag vocabulary

The `exit` tag group (`app_logic.TAG_GROUPS`) currently has two values:
`Planned — Monitored Continuation`, `Fear / Anxious`. Seed additional defaults so the exit
reason becomes a countable dimension:

- `Target hit`
- `Target never reached`
- `Stopped out`
- `Greed / chased`
- `Time stop`
- `Management error`

The group stays `multi: False`. Tag config is already user-editable in Settings, so the list
can be tuned afterward without code changes. Existing tagged trades are untouched.

**Demoted by §6.** In an earlier draft this vocabulary carried the fear/greed verdict, because
it was the only available substitute for missing price data. With the peak recorded, the data
answers that question directly, so the tags become **corroboration and narrative** — they say
*why*, while §6.5 says *what was available*. Two consequences:

- `Target never reached` is now **derivable** (`sign*(P - T) < 0`). Offer it as an auto-suggested
  tag rather than relying on it being applied by hand.
- Where a tag and the peak disagree — e.g. tagged `Target hit` but `sign*(P - T) < 0` — the peak
  wins for classification, and the row is flagged for review rather than silently reconciled.
  A disagreement usually means one of the two was recorded carelessly, which is worth seeing.

---

## 8. Weekly page (`weekly_review.html`)

New `PLAN vs EXECUTION` section. The existing Trade ledger and Setup performance table stay
exactly as they are.

**Roll-up strip** (top), in three bands:

1. **Buckets** — four tiles (count, net $, avg capture % each) plus the `No plan · N` count.
   Computed over all trades with a target, peak or no peak.
2. **Verdicts** — the §6.5 three-way split of `Cut Early`: `Froze at target`, `Bailed early`,
   `Market didn't pay`, each with count and net $. Computed over the **covered set only**,
   headed by the coverage line `peak recorded on 14 of 19 trades` (§6.6).
3. **Excursion & realism** — total give-back $, total missed-run $, and target realism
   (share of covered trades where the target was ever offered).

The fear/greed headline is drawn from band 2, not from capture % and not from tags:

- **Fear signal** = `Froze at target` + `Bailed early`, e.g. *"3 trades cut at an average 58%
  of plan while the target was on the table — $412 of available move left behind."*
- **Greed signal** = `Ran Past` trades that ended net negative, plus give-back on trades that
  were meaningfully green at their peak and closed red.
- **Not a signal** = `Market didn't pay`. Explicitly excluded from the fear count.
- **Separate finding** = low target realism. Reported next to the headline, never folded into
  it — targets set too far out look identical to fear in capture % and need the opposite fix.

When a band has no qualifying trades, its clause is omitted rather than rendered as a zero.
When coverage is zero for the week, bands 2 and 3 are hidden entirely rather than shown empty.

**Table**: twelve columns will not fit, so each trade renders as **two rows** — numbers on top,
free text beneath:

```
Date  Setup            Level  Stop     Plan     Actual   Peak       Capture  Verdict          Size/Risk  Emotion
Jul 8 Recapture VWAP   VWAP   7688.50  7760.00  7731.25  7772 dur   0.60     Froze at target  3 · $398   eager
      in: strong buying volume after reclaim · out: pulled it when it stalled at the half-back
```

`Peak` shows the price plus a compact `dur`/`aft` timing marker, or a dash when not recorded.
`Verdict` is the §6.5 value, or the plain §5 bucket when no peak exists. The exit tag moves
into the free-text row (`out:` prefix) to make room, since §7 demoted it to narrative.

Other column sources: `Level` from the `with` tag group; `Emotion` from
`guard_json.mental_state` plus `pre` tags; `in:` from `trades.notes`; `out:` from the exit tag
plus `trades.notes_exit`, verbatim.

Reads journal trades only, consistent with the rest of the weekly page. An open live trade
appears after it is pushed.

---

## 9. Out of scope

- **No new trajectory detector** for cut-early. It would fit `DETECTOR_REGISTRY` naturally and
  give a cross-week trend, but it changes `insight_log` semantics and needs a backfill run.
  Revisit once several weeks of target data exist to calibrate the band against.
- No editing of targets on the journal side after push. The columns support it; this spec
  keeps the change to the live/Manage flow and the weekly read.
- No change to working stop/TP behavior, the right-panel net-risk math, or `initial_risk`.
- No **automatic** peak capture. §6 records it by hand precisely because there is no price
  feed; an automated version would need market data this app does not have.
- No max **adverse** excursion (how much heat was taken before the trade worked). It is the
  natural sibling of §6 and would speak to stop placement, but it doubles the input burden on
  the strip. Revisit once the peak strip has proven it gets filled in consistently.
- No editing of trades beyond the single `/mfe` field. This spec adds one numeric-field route,
  not a general trade editor.

---

## 10. Testing

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

Peak capture (§6):

- Migration re-runnable for the three `trades` columns.
- `POST /api/trade/<id>/mfe` stores price and timing, and stamps `mfe_window_minutes` from
  config; a client-supplied window is ignored.
- `mfe_timing` outside `during`/`after` returns `400`.
- Re-posting a peak overwrites it (no freeze), unlike the target route.
- Strip lists all closed trades lacking a peak, winners and losers, including earlier days;
  a trade disappears from the strip once saved.
- Verdict split: long and short; `P` exactly equal to `T` falls in the offered branch
  (`>= 0`); `during` vs `after` select `Froze at target` vs `Bailed early`.
- Excursion sign is correct for shorts, and give-back on a stopped-out loser is positive.
- Coverage: bucket percentages use all targeted trades, verdict and realism percentages use
  the covered set only; a week with zero coverage hides bands 2 and 3 rather than rendering
  0/0.
- A trade with a target but no peak still renders its §5 bucket and no verdict.
