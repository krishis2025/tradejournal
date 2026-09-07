# Planned exit capture — known follow-ups

Recorded at the end of the 2026-09-06 implementation run. Everything here was found by review,
deliberately not fixed, and triaged as safe to leave. Ordered by value.

## Worth doing before heavy tag editing

- **`save_tag_config` reads a deletion as a rename** (pre-existing, `database.py` ~1546).
  It diffs tag lists **by position**, so deleting a tag makes its successor look renamed and
  `_cascade_tag_rename` relabels trades carrying it. This feature takes the exit group from 3
  tags to 9, which makes the scenario reachable for the first time. Pruning one of the six new
  exit tags in Settings could silently relabel real trades.

## Worth doing before any deployment work

- **`get_instrument_config()` runs up to twice per row** inside `build_plan_execution`'s loop
  (~1.7ms each, ~65ms on a 20-trade week) — an N+1 inside the very loop whose fills query was
  deliberately batched. Hoist it above the loop. Fix alongside the **pre-existing** tag N+1 in
  `get_trades_in_range`, which issues one query per trade in the same request and is larger.

## Spec items delivered short

- **A saved peak cannot be corrected in the UI.** Spec §6.3 says a wrong peak "should be
  fixable" and the route allows overwrite, but PLAN CHECK lists only rows where `mfe_price IS
  NULL` and disables the input on save. A typo is currently correctable only via `curl`.
  Needs a design decision about the surface, not a patch.
- **The `Emotion` column** specified in spec §8 is absent from the weekly table. The data
  (`guard_json.mental_state` + `pre` tags) is already loaded on every trade.
- **The greed signal implements one of spec §8's two clauses** — `Ran Past` trades that closed
  red. The second (give-back on trades meaningfully green at their peak that closed red) is the
  one the peak data uniquely enables. Give-back is still reported as its own tile.

## Cosmetic

- **Hardcoded palette colors** across all three new surfaces (`var(--mint, #4fffb0)` — `--mint`
  is defined nowhere, so it always falls through). The app ships ten themes including a light
  "paper" theme on which those markers are close to illegible.
- The exit-tag migration has **no version marker**, so a deliberately deleted canonical exit tag
  re-appends on the next request. Inherent to the append-only design.
- Plain `INSERT` against `UNIQUE(group_id, tag)` in that migration could collide on two
  concurrent first-run requests (self-healing on retry; `INSERT OR IGNORE` closes it).
- Dead `ideaRisk` variable at `templates/live_v2.html` ~7294.
