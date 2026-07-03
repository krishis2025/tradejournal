# Reference — Detector spine, insight_log & trajectory states

> **What this is:** the durable reference for the coaching system's backbone — the detector IDs,
> the `insight_log` table, and the trajectory states. Open this when you want to enhance or change
> the logic. It's the map of how tags become tracked patterns.
>
> **Status:** written from the agreed design. Items marked **⚠ VERIFY** must be checked against the
> live code (final spellings / column types / thresholds may have shifted during implementation).
> Run this past Claude Code once for a literal-accuracy pass.

---

## 1. The mental model (the spine)

Everything flows one direction. **The detector ID is the shared key** that ties firing, logging, and
intention-targeting together — that's why it has to be one canonical spelling everywhere.

```
  TAGS (many, messy)        DETECTORS (~10, fixed IDs)       INSIGHT (a sentence)      INSIGHT_LOG (history)
  ──────────────────        ──────────────────────────       ────────────────────      ─────────────────────
  "No Setup"          ┐
  "Eager to trade"    ├───►  impulsive_bucket  ──────────►   "3 impulsive trades   ──►  1 row per detector
  "Revenge Mindset"   ┘      (owns its own tag logic)         netted -$544"              per week, keyed by
                                                                                          detector_id
  "Trade came to me"  ─────► came_to_me        ──────────►   "patience held"       ──►   │
  "Operational Error" ─────► operational_error ──────────►   "$8,000 was a size    ──►   │  detector_id is
   ...                        ...                              error, not a trade"        ▼  the SPINE
                                                                                    weekly_intentions.targets
                                                                                    points at a detector_id too
```

Key consequences:
- **Tags never reach the tracking layer.** They're absorbed *inside* a detector. Change a tag → edit
  one detector, nothing downstream cares.
- **The detector list is the vocabulary.** ~10 fixed IDs. Logging, trajectory, and intentions all
  speak only this language.
- **"Is my intention working?"** is a join: `intention.targets` → that detector's rows in `insight_log`.
  No text parsing, no model.

---

## 2. Detector registry — the canonical IDs

The single source of truth is a registry constant in `app_logic.py` mapping each ID to
`{label, polarity, tracked}`. **⚠ VERIFY** these spellings match the code after the ID rename.

### Tracked patterns (appear in Trajectory) — 8

| detector_id | label (UI) | polarity | fires on (the rule it owns) |
|---|---|---|---|
| `impulsive_bucket` | Impulsive trades | leak | trades tagged Eager / Revenge / Quick-Profit net negative or material |
| `revenge_chain` | Revenge after loss | leak | a Revenge/Eager trade taken right after a loss > trailing avg loss (same day) |
| `no_setup_leak` | No-setup leak | leak | trades tagged "No Setup" net negative & material |
| `weak_exits` | Fear / bailed exits | leak | fear/anxious/bailed exit tags net negative & material |
| `expectancy_gap` | Losses bigger than wins | leak | win rate ≥ 50% but net < 0 (avg loss > avg win) |
| `operational_error` | Operational error | leak | any trade tagged "Operational Error" |
| `oversized_loss` | Oversized loss | leak | a single trade's loss > 5× trailing avg loss |
| `came_to_me` | Came to me (patience) | **strength** | trades tagged "Trade came to me" — tracked for *sustained / declining* |

### Weekly-only detectors (fire in the story, NOT tracked) — 2

| detector_id | label | why not tracked |
|---|---|---|
| `net_result` | Net result | it's the headline, not a habit |
| `concentration` | Concentration / sign-flip | week-to-week variance, not something you "improve at" |

> **Note on overlap (not a bug):** one trade can carry *both* a No-Setup tag and an impulsive tag, so
> `no_setup_leak` and `impulsive_bucket` can count the same trade and report identical magnitudes in a
> given week. Per-detector counting is correct — it just reflects that your no-setup trades and your
> impulsive trades are often the same trades.

---

## 3. `insight_log` — the history table

One row **per tracked detector, per week, per account**. This is the only durable record of trajectory.
**⚠ VERIFY** column names/types against the migration.

```
insight_log
┌──────────────┬─────────┬──────────────────────────────────────────────────────────┐
│ column       │ type    │ meaning                                                    │
├──────────────┼─────────┼──────────────────────────────────────────────────────────┤
│ id           │ INTEGER │ pk                                                         │
│ account_id   │ INTEGER │ FK accounts(id) ON DELETE CASCADE                          │
│ week_start   │ TEXT    │ Monday of the week, ISO (e.g. 2026-06-22) — the time bucket │
│ detector_id  │ TEXT    │ the SPINE — which pattern this row is about                 │
│ fired        │ INTEGER │ 0/1 — did the pattern trigger this week                     │
│ magnitude    │ REAL    │ signed $ impact that week (leaks negative, strength +)      │
│ count        │ INTEGER │ supporting count (e.g. # impulsive trades)                  │
│ qualifying   │ INTEGER │ 0/1 — did the week meet the trade floor (≥5). Light/no-trade │
│              │         │ weeks = 0 and DON'T count toward fired/not-fired stats      │
│ created_at   │ TEXT    │ timestamp                                                  │
└──────────────┴─────────┴──────────────────────────────────────────────────────────┘
UNIQUE (account_id, week_start, detector_id)   ← idempotent upsert key
```

Example (one week, a few detectors):

```
account_id  week_start   detector_id        fired  magnitude  count  qualifying
7           2026-06-22   impulsive_bucket   1       -544       3      1
7           2026-06-22   no_setup_leak      1       -544       2      1
7           2026-06-22   came_to_me         1       +925       4      1
7           2026-06-22   revenge_chain      0          0       0      1
7           2026-06-22   weak_exits         0          0       0      1
   ...      (every tracked detector gets a row each qualifying week, fired=0 included)
```

> **Completeness rule:** each qualifying week should have a row for *every* tracked detector, with
> `fired=0` for the ones that didn't trigger — not just rows for the ones that fired. A silently-missing
> detector reads as "never a problem" forever.

---

## 4. Intention linkage

`weekly_intentions.targets` (**TEXT**) holds a `detector_id` (or `''` / `'general'` for self-graded-only).
Stamped at creation — proposed intentions inherit the proposing detector's ID; self-authored ones pick
from a dropdown of the 8 tracked labels.

```
weekly_intentions                          insight_log
┌──────────────────────────┐               (rows for that detector,
│ text: "no trade after a  │   targets      since intention.created_week)
│        hard loss"        │  ──────────►   revenge_chain: fired, fired, 0, 0, 0
│ targets: revenge_chain   │                        │
│ source: proposed         │                        ▼
│ result: pending          │                "hasn't fired since you set it → working ✓"
└──────────────────────────┘
```

`targets=''` → manual held/broke only, no auto-verification (no detector to measure against).

---

## 5. Trajectory states

Two axes — keep them separate, this is what caused confusion:

```
        FREQUENCY  (how OFTEN it fired)              TREND  (which DIRECTION magnitude is going)
        shown as: "fired 7 of last 8 weeks"         shown as: the badge + sparkline shape
        ── a count over the trend window ──         ── slope of recent firings ──
```

A pattern can be **high-frequency AND improving** (fires almost every week, but magnitudes shrinking).
The **badge = trend**, the **count = frequency**. They are different numbers answering different questions.

### Leak states

| state | meaning | rough rule (⚠ VERIFY thresholds) |
|---|---|---|
| **New** | first appearance | fired this week, not in prior weeks of recurrence window |
| **Recurring** | becoming a habit | fired this week AND ≥1 other week in recurrence window (4 wk) |
| **Chronic** | defining leak | fired in ≥ ~60% of qualifying weeks in trend window (8 wk) |
| **Improving** | shrinking | fired, but |magnitude| trending down over recent firings |
| **Resolved** | beaten | was Recurring/Chronic, no fire in last ~3 qualifying weeks |

Precedence when several apply: **Resolved > Improving > Chronic > Recurring > New**.

### Strength states (came_to_me — everything inverts)

For a strength, "stopped firing" is **bad** (good habit going quiet), and the trend reads the opposite way.

| state | meaning |
|---|---|
| **Building** | strength growing (magnitude trending up) |
| **Holding** | steady |
| **Slipping** | good habit declining (magnitude trending down / firing less) |

> Word choice: use **Slipping**, never "fade/fading" — "fade" collides with the trading term (balance fade).

### Bucketing in the UI

```
STILL REPEATING        IMPROVING / BEATEN        STRENGTHS
  Chronic                Improving                  Building
  Recurring              Resolved                   Holding
                                                    Slipping
```

---

## 6. Windows & config (⚠ VERIFY defaults in code/settings)

| knob | default | what it controls |
|---|---|---|
| recurrence window | 4 weeks | New vs Recurring; "did this repeat" |
| trend window | 8 weeks | Chronic / Improving / Resolved; the sparkline span |
| qualifying floor | 5 trades/week | a week must hit this to count as fired/not-fired |
| chronic threshold | ~60% of qualifying weeks | Recurring → Chronic boundary |
| visible cap | 2 + 2 | top repeating + top improving shown; rest queryable |
| zone gate | ≥ 4 qualifying weeks | below this, hide zone / show "building — N of 4" |

All windows are **rolling**, not calendar months (a calendar reset would break streaks mid-pattern).

---

## 7. ⚠ VERIFY checklist (for Claude Code's accuracy pass)

1. The 8 tracked + 2 untracked detector IDs match §2 spellings exactly (post-rename, single canonical form, no aliases).
2. `insight_log` columns/types/UNIQUE key match §3.
3. State thresholds match §5 (chronic %, resolved "last N", recurrence definition).
4. `weekly_intentions.targets` exists and holds a detector_id.
5. Defaults in §6 match settings/constants.
6. Completeness: a `fired=0` row is written for every tracked detector each qualifying week.

---

## 8. Open / pending decisions

- **Frequency-vs-trend boundary (UNRESOLVED):** should a leak that fires in most weeks be forced into
  "Still Repeating" even if its magnitude is improving? Currently the trend wins (it can show as
  Improving despite high frequency). Decide whether high frequency overrides an improving trend, and
  update §5 once settled.
- **"fired N wk" label:** reword to "fired N of last M weeks" so it reads as a count, not "N weeks ago."

- **Conditional denominators for frequency (tracked follow-up — NOT built, deferred on purpose):**
  Some behaviors are *conditional* — they can only occur in certain situations — so measuring their
  frequency against *total trades* is a category error that can mislead. The clearest case is
  **`revenge_chain`**: revenge is only possible *after a loss*, so its true rate is
  **revenge trades ÷ losing trades** ("revenge trigger rate: of the losses where revenge was possible,
  how often did I take the bait"), not revenge trades ÷ total trades. With the current total-trades
  denominator, a low-loss (green) week makes revenge % drop and can read as "improving" when discipline
  didn't change — you just had fewer opportunities to revenge-trade.
  - **Current state (know this):** revenge frequency is measured against **total trades** today, so it
    may read falsely rosy on low-loss weeks. Don't over-trust a "revenge improving" verdict on a
    light-loss week.
  - **Why deferred:** revenge is the sparsest detector (fired ~4 of 8 weeks) and currently has a
    state-classifier bug; the user's tagging behaviour is also about to change (observing Intuition/Mkt
    Feel usage). Refining the denominator on thin, shifting, still-buggy data is premature. Fix the
    state bug and let it stabilize first.
  - **When revisited, decide:** (a) revenge-only special case vs. a general "a detector declares its own
    frequency denominator" mechanism — other conditionals may want this (e.g. `weak_exits` as % of
    exits, `no_setup_leak` as % of discretionary entries); decide once 2–3 detectors actually want it,
    not by generalizing from one. (b) A **conditional qualifying floor** — revenge's denominator
    (losing trades) is small, so a week needs enough *losses* (propose ≥3) to count, and a zero-loss
    week is "not applicable" (skipped), not 0%. Severity (cost per revenge trade) is unaffected — only
    the frequency axis changes. Verdict sentence would reframe to "…after 11% of your losses."

- **Severity axis is size-contaminated — migrate to R per occurrence (tracked follow-up — NOT built,
  same dependency as risk/R analytics):**
  The two-slope engine's **severity** axis is measured in **dollars per occurrence**, and dollars scale
  with risk size. If your risk grows across the window (e.g. $200/trade in the first 4 weeks → $400/trade
  in the last 4 — natural as the account grows), the *same behavioral mistake* costs ~2× the dollars in
  the second half, and the engine reads "severity worsening" when the *behavior* didn't change at all.
  This is the same size-contamination that frequency was designed to avoid — it snuck back in through
  severity.
  - **Current state (know this):** severity-in-dollars is only trustworthy while risk size is roughly
    **flat** across the 8-week window. On a window where you sized up, discount any "severity worsening"
    verdict — cross-check it against the frequency axis (which is size-proof). Only the severity half is
    affected; frequency stays honest, so the two-axis design contains the damage to one axis.
  - **The fix:** measure severity as **R per occurrence** (dollars ÷ captured risk-per-trade) instead of
    dollars. R is size-normalized by construction — a −1R mistake reads the same whether risked at $200
    or $400 — so first-4-vs-last-4 severity becomes apples-to-apples regardless of account growth.
  - **Why deferred:** R needs captured stop data, and historical stops are essentially unpopulated
    (stop-capture was forward-looking). So severity-in-R **can't be backfilled** — it activates as
    captured-stop data accumulates. This is the **same dependency** as the parked risk/R weekly visuals,
    so fold severity→R into that work when it happens rather than as a separate effort.
  - **Interim option (optional bridge):** if wanted before per-trade stops mature, normalize dollar
    severity by the *period's average risk* — cruder than true R (uses an average, not each trade's
    actual risk) but removes most of the size drift.

- **Entry-type edge analytics** (tracked follow-up, *not* in this system): "does entering on strength
  pay?" is an edge/expectancy question for the analytics surface, R-based, separate from trajectory.
  (Note: shares the same captured-stop dependency as severity→R above.)
