# Planned exit capture — known follow-ups

Recorded at the end of the 2026-09-06 implementation run. Everything here was found by review,
deliberately not fixed, and triaged as safe to leave. Ordered by value.

## Fixed

- **`save_tag_config` read a tag deletion as a rename** (`database.py`). Settings sends only an
  ordered list of strings, so a rename and a deletion are indistinguishable by position — deleting
  a tag shifts later tags up a slot, and the rename cascade then relabelled the deleted tag's
  trades. Reproduced on a copy of the real journal: deleting `Fear / Anxious` silently moved 11
  trades to `Bailed out - Reasses`. Fixed by cascading only when the list length is unchanged, since
  a pure rename cannot change it. Covered by `tests/test_tag_config.py`.

  Note: this bug predated the planned-exit feature and was **not** made reachable by it — the same
  deletion destroyed the same 11 trades against the original three-tag vocabulary. An earlier
  version of this document said otherwise; that was wrong.

## Low priority — measured, not worth doing on its own

- **`get_instrument_config()` runs up to twice per row** inside `build_plan_execution`'s loop —
  an N+1 inside the very loop whose fills query was deliberately batched. The review estimated
  ~1.7ms per call and ~65ms per week; measured against real data it is **0.52ms per call**, and the
  busiest week in this journal is 19 trades, so the true cost is **~20ms**. `build_plan_execution`
  is 2.6ms of a 30ms weekly page build — under 9%. The pre-existing tag N+1 in `get_trades_in_range`
  is 2.1ms, not the larger problem the review assumed.

  Worth doing for consistency if that loop is touched again; not worth a diff on its own. The real
  scaling risk is not these loops but that `get_conn()` opens a fresh connection per call across the
  whole app — a connection-pooling concern, not an N+1 one.

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
