# A/B/C game grading & diagnostic tags

**Date:** 2026-09-07
**Status:** Approved design, ready for implementation planning
**Version target:** 4.9.0
**Source framework:** *Trading Journal Scoring Framework v2* (Jared Tendler A/B/C game analysis;
Steenbarger; SMB/Bellafiore; Van Tharp). Section references below (§n) are to that document.

## Goal

Replace the 5-point execution score with **one A/B/C grade per trade plus a small number of
diagnostic tags**, so the journal answers *which version of me showed up* rather than producing a
number nobody acts on.

The framework's own statement of the target (§1): *track the components, but do not score every
component.* And (§10): the point is not artificial precision like an average entry score of 2.73 —
it is to identify recurring causes of performance degradation.

## The four questions this must answer (§10)

1. What most often turns my A-game into B-game?
2. Which emotions are associated with premature exits?
3. What creates my C-game?
4. Are my targets reasonable?

Question 4 is not in the framework; it is the user's addition and drives the second ratio in §7 below.

## Governing principles

- **P&L has no vote** (§2). A losing trade can be A-game; a profitable trade can be C-game. No
  derived grade, no colour, and no headline may take P&L as evidence of execution quality.
- **The exit is a management decision** (§3). Once the position is open, everything until flat —
  holding, stop moves, scaling, partials, the final exit — is Trade Management. There is no separate
  exit score.
- **An early exit is not automatically a mistake** (§7). "Early Exit" means *premature or unjustified
  relative to process*, never "price continued after I got out". This constrains the whole design:
  price data describes, the trader judges.
- **Keep live journaling light** (§9). During the session record the minimum; diagnose afterwards.
  The existing closed-but-unpushed state already provides that window.
- **Nothing derived is persisted.** Ratios, colour bands, distributions and cross-tabs are all
  computed on read — consistent with the rest of this codebase.

---

## 1. Data model

Five new columns on **both** `live_trades` and `trades`, added with the project's guarded
`ALTER TABLE` pattern inside `init_db()`, and carried across on push exactly like `market_state_json`
and the `mfe_*` columns:

| Column | Type | Values |
|---|---|---|
| `grade` | TEXT | `A` \| `B` \| `C` \| NULL (not graded) |
| `management` | TEXT | `followed` \| `deviated` \| NULL |
| `management_issue` | TEXT | `none` \| `early_exit` \| `late_exit` \| `stop_change` \| `overmanaged` \| `under_managed` \| `premature_scale_out` \| NULL |
| `emotion` | TEXT | one of the eight in §3 \| NULL |
| `process_violation` | TEXT | `none` \| `traded_outside_plan` \| `exceeded_risk` \| `revenge_trade` \| `overtraded` \| NULL |

Plus two more:

| Column | Type | Purpose |
|---|---|---|
| `emotion_entry` | TEXT | The pre-entry emotion (§3), replacing `trade_strength.mental_state` |
| `pre_tags_late` | INTEGER | `0`/`1`. Set to 1 when pre-trade tags are first filled at review rather than at entry. |

**Columns, not a JSON blob — deliberately.** Every question in §10 is a `GROUP BY` over two of these
fields. As JSON they would need parsing per row in Python on every weekly render; as columns they are
one query. The existing `execution_score_json` is precisely the blob shape that makes those questions
awkward today.

**NULL means not recorded, and is never coerced.** Historical trades carry NULL for all seven. Every
distribution over them reports coverage (§6), the same rule the peak capture already follows.

---

## 2. Grade (§2, §8)

Chosen by the trader — never derived. A formula cannot see which version of you showed up, and a
derived grade would recreate the number this design exists to remove.

The three definitions appear as helper text under the buttons, verbatim from §8:

- **A** — The opportunity came to you; you entered intentionally; risk and size were appropriate;
  management decisions were justified by your process and the information available at the time. A
  technical read can still turn out to be wrong.
- **B** — The core process remained recognisable, but there was minor emotional or execution leakage:
  entering somewhat early, hesitation, overmanagement, or an emotion-driven early exit.
- **C** — A meaningful breakdown: forced trade, chase/FOMO entry, revenge trading, inappropriate risk,
  moving a stop because you could not accept the loss, major overtrading, or another obvious
  abandonment of process.

The reminder **"P&L has no vote — a losing trade can be A-game"** sits with the control.

---

## 3. Emotion — one vocabulary, two moments

The eight values (§4): `calm`, `fear_of_loss`, `fear_of_giving_back`, `greed`, `frustration`,
`impatience`, `overconfidence`, `distracted`.

- **At entry** (`emotion_entry`) the picker offers only the six that can precede a trade: calm,
  impatience, frustration, greed, overconfidence, distracted. `fear_of_loss` and
  `fear_of_giving_back` both require an open position, so offering them before entry invites a
  nonsense answer.
- **At review** (`emotion`) all eight are offered.

This retires `trade_strength.mental_state` (calm/fomo), which is too coarse to trace an entry state
through to a management deviation. The column is kept and left unread.

> Note: `guard_json.mental_state` (patient / intuition / eager) belongs to the ENTER-key guard
> overlay and is a **different field**. It is out of scope and unchanged.

---

## 4. Screens

### 4.1 Assessment page (`live_v2.html`)

Keeps its structure — the deliberate friction is the point. Changes:

- The **Patience** tile is relabelled **"Trade came to me"**, keeping its current visual treatment.
  Its helper text becomes "I waited for my level." The underlying column stays named `patience`
  (no migration).
- Ticking that tile **also sets the `pre` tag "Trade came to me"**, so the four existing consumers of
  that tag keep working untouched: the weekly `came_to_me` detector (`app_logic.py` ~1871),
  `PRE_GOOD` in `day.html`, and two places in `analytics.html`.
- **Source of truth: the tag.** The tile and tag can drift — ticked at entry, unticked at review.
  Everything analytical reads the tag; `patience` feeds only its own `0/3` counter. Two-way sync is
  deliberately not built.
- `MENTAL STATE: CALM / FOMO` is replaced by the six-value entry emotion picker (§3).
- The right panel gains **Setup** and **Pre-trade** pickers.
- The `0/3 process · 0/4 technical` counters remain, as context only. They are not a score.

### 4.2 Entry form

Unchanged.

### 4.3 Review page (`live_v2.html`)

**Removed:** the `n/5` execution-score hero; the Management block (Calm & objective / Anxious /
Frozen / Overconfident); the separate Exit-discipline block (§3 folds the exit into management).

**Added, in this order:**

1. **Grade** — A / B / C with the §8 definitions and the P&L reminder.
2. **Management** — Followed process / Deviated.
3. **Management issue** — shown **only when Deviated**. Seven values (§1).
4. **Emotion** — all eight.
5. **Process violation** — shown **only when the grade is B or C**. Five values.

Gating 3 and 5 keeps an A-game trade to two clicks. A field answered `none` nine times in ten is one
that stops being read.

**Kept:** the entry recap (recorded at entry, not editable), the notes fields, and the right panel —
Technicals, Volume, Setup, Pre-trade. Setup and Pre-trade are editable here as well as at entry; when
pre-trade tags are first filled here on a trade that had none at entry, `pre_tags_late` is set to 1.

---

## 5. The two ratios

Both are derived on read from stored prices. Neither carries a verdict word.

```
capture    = sign * (avg_exit - avg_entry) / (sign * (target - avg_entry))     # existing
target_fit = sign * (mfe_price - avg_entry) / (sign * (target - avg_entry))    # new
```

`sign` is +1 long / -1 short; both share the existing `PLAN_EPSILON` guard and return `None` when
there is no target or the target sits within one tick of entry.

### 5.1 Capture — *did I wait for my plan?*

Rendered as the number with a colour band. **Blank when the trade lost** (`pnl < 0`), because a
capture ratio on a losing trade compares an exit against a target that was never in play. A scratch
(`pnl == 0`) still renders its capture — it is not a loss.

| capture | colour |
|---|---|
| `< 0.60` | dark red |
| `0.60 – 0.80` | orange |
| `0.80 – 1.10` | dark green |
| `> 1.10` | blue |

These bands **nest inside the existing buckets** — `plan_capture_low` (0.60) and `plan_capture_high`
(1.10) keep their current values and their current meaning, and `0.80` merely splits `at_plan` into
"scraped it" and "took it". No bucket changes and no reclassification of any trade; the only addition
is one config key `plan_capture_mid` (default 0.80) for the new split, named consistently with its
neighbours.

### 5.2 Target fit — *was my plan reasonable?*

| target_fit | label |
|---|---|
| `< 0.80` | target too far |
| `0.80 – 1.20` | well calibrated |
| `> 1.20` | target too close |

Two new config keys: `target_fit_low` (0.80), `target_fit_high` (1.20).

**Reported as a weekly distribution, not as a per-row column.** Read one row at a time it is
hindsight — price running 130% past a target does not prove that target was wrong on that trade.
Read across twenty trades it is genuinely diagnostic, which is what question 4 needs. The per-row
value is available in the payload but not rendered in the table.

Requires a recorded peak, so it spans the covered set only (§6).

**Target fit is independent of the capture blanking rule.** A losing trade shows no capture but still
contributes a target fit, because "was my target reasonable" is a fair question on a loser — the peak
and the target are both known regardless of how the trade ended.

---

## 6. Coverage

Three independent denominators already exist and must not be conflated:

- `coverage.covered` — trades with a recorded peak
- `realism.of` — trades with both a target and a peak
- `graded_of` — **new** — trades with a grade

Every distribution states its own denominator in words. A grade distribution over 4 of 9 trades says
so; percentages are computed over the graded set only, never over all trades.

---

## 7. Weekly page

- `Avg Exec Score` tile → **grade distribution**: A / B / C counts with net $ each, plus
  `graded N of M trades`.
- Plan-vs-Execution table: drop the `Verdict` column, add **P&L**, colour the Capture number per
  §5.1. The table currently shows risk in `Size/Risk` and never shows the result — P&L closes that.
- Above the table: the **target-fit distribution** (§5.2).
- **The fear/greed headline is deleted.** It accused the trader from price data alone, which §7
  forbids. The grade and Management Issue now carry that judgement.
- **Kept:** give-back and missed-run (dollar facts, not verdicts) and the peak coverage line.
- **New diagnostic block**, answering §10 questions 1 and 3 directly: across B and C trades, the most
  common `management_issue` and the most common `emotion`. Not a general pivot table — two counts.
  Hidden entirely when the week has no B or C trades, rather than rendered empty.

**Day page:** `compute_combined_day_score` drops its execution component and reflects the day process
checklist alone. Trade trays show the letter grade.

---

## 8. What this supersedes

Nothing is deleted from the database. Old trades keep what they recorded; new code stops reading it —
the same treatment `plan_capture_band` received.

| Retired | Replaced by | Historical data |
|---|---|---|
| `execution_score_json` (5-point) | `grade` | Kept, unread |
| `exit` tag group | `management_issue` + `emotion` + target fit | Tag rows kept on old trades |
| `exit_tag_signals`, `tag_conflict`, `tag_suggestion` | Target fit, shown as a number | n/a — derived |
| `classify_verdict`, `verdicts`, `verdicts_of`, `fear`, `greed` | The two ratios | n/a — derived |
| `trade_strength.mental_state` | `emotion_entry` | Kept, unread |

The `exit` tag group is removed from `TAG_GROUPS` defaults. Because `get_tag_groups()` returns a DB
override wholesale when one exists, the removal must also drop the group's `tag_config` rows —
otherwise the retired vocabulary keeps being served from the override. That deletion is the one
destructive step in this spec and must be flag-guarded and one-shot, and it must not touch
`trade_tags`, so historical trades keep their exit tags.

> The rename-by-position hazard in `save_tag_config` is fixed as of 4.8.1, so removing a group is
> safe. Do not route this deletion through `save_tag_config` regardless — it opens its own connection
> and would deadlock inside `init_db()`.

**Interaction with the 4.8.2 append migration.** Version 4.8.2 added a one-shot, flag-guarded
migration that *appends* the widened exit vocabulary into `tag_config`. This spec's deletion must run
**after** it in `init_db()`, and must not clear that migration's flag — otherwise on a fresh database
the append would re-add the very rows this one removes, on the following request, forever. Both
migrations are flag-guarded and one-shot, so the correct end state is: append ran once, delete ran
once, and neither runs again.

---

## 9. Out of scope

- **No derived or suggested grade**, and no flag when the grade disagrees with the other fields. The
  judgement is the trader's; an app arguing with it defeats the purpose.
- **The PDF's `Trade came to me? Yes/No` and `Entry Quality` fields.** The relabelled Patience tile
  and the entry emotion picker already cover them, recorded *before* entry where they act as a brake
  rather than after, where hindsight is free.
- **No backfill of grades onto historical trades.** A 3/5 was never a judgement about which game was
  being played; converted letters would be fabricated history indistinguishable from real ones.
- **No change to the ENTER-key guard overlay** or `guard_json`.
- **No general cross-tab / pivot UI.** Two counts (§7), not a query builder.

---

## 10. Testing

- Migration re-runnable: `init_db()` twice adds one copy of each column and deletes the `exit`
  `tag_config` rows exactly once.
- The `exit` group deletion leaves `trade_tags` untouched — a trade tagged `Fear / Anxious` still is.
- Push carries all seven new fields from `live_trades` to `trades`.
- Ticking the relabelled tile sets the `pre` tag; the weekly `came_to_me` detector still fires.
- Tile and tag disagreeing resolves to the tag.
- `pre_tags_late` is set only when pre-trade tags were absent at entry and present after review.
- Entry emotion picker rejects `fear_of_loss` / `fear_of_giving_back`; review accepts all eight.
- `management_issue` is only accepted when `management = 'deviated'`; `process_violation` only when
  grade is B or C.
- Capture colour bands at exactly 0.60, 0.80, 1.10; blank when `pnl < 0`.
- `target_fit` for long and short; boundaries at exactly 0.80 and 1.20; `None` without a peak.
- Grade distribution reports `graded_of`, and percentages use it — not the trade count.
- A week with no graded trades hides the distribution rather than rendering zeros.
- Pre-feature trades (NULL grade, no peak, no target) render on both pages without error.
