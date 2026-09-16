# Session handoff

**Status as of 2026-09-16: configurable review markers (v4.12.0) is complete and verified.**
Nothing is in progress.

An earlier revision of this file described a fix wave that was implemented but unverified. That
state is gone — the verification ran, all ten mutations caught their bug, one genuine coverage gap
was found and closed, and the work is pushed.

## What shipped

| Version | Change |
|---|---|
| 4.11.0 | Weekly market board — 20 instruments, percent from Monday's open |
| 4.11.1 | The board updates as you type instead of only on reload |
| 4.12.0 | **Configurable review markers** — five review vocabularies editable in Settings, with emotions and process violations multi-select |

## Where to look

- **Spec:** `docs/superpowers/specs/2026-09-15-configurable-review-markers-design.md`
- **Plan:** `docs/superpowers/plans/2026-09-15-configurable-review-markers.md`
- Earlier feature: `docs/superpowers/specs/2026-09-14-weekly-market-board-design.md`

## On first app start after pulling

Two guarded migrations run automatically, because `data/journal.db` is gitignored and never travels
with the code:

1. `tag_config` gains `tag_key`, `locked` and `at_entry`. Legacy rows keep `tag_key` NULL and are
   untouched.
2. `emotion` and `process_violation` on `trades` and `live_trades` are wrapped from single values
   into JSON arrays (`greed` → `["greed"]`). Guarded by a flag AND by a `NOT LIKE '[%'` filter, so a
   lost flag cannot double-wrap. Verified idempotent against a copy of the real journal.

## Still needs human eyes — no JS test infrastructure exists

1. Settings → Tags → **Review Markers** is the second tab; all five cards render in two columns.
2. Rename "None" under Process violation to "Clean", save, reload — the review chain shows "Clean",
   and grading a trade **A** with it selected still saves.
3. Locked rows offer no ✕ but stay renamable; deleting an unlocked option removes it from the chain.
4. Add an emotion with **entry** ticked — it appears on the pre-entry question and looks selected
   when chosen. Untick it: gone from entry, still in the review.
5. Select two emotions on one trade, reload, both come back selected.
6. "None" under Process violation clears the others, and picking a real violation clears "None".
7. Toggle Multi-select off for Emotions, save, reload — the chips become single-select.
8. Toggle Multi-select on Technicals, save, reload — it now stays on. It never did before.

## Known, accepted

- **Changing an unlocked tag's key** (not its label) orphans trades that stored the old key. Accepted:
  it is indistinguishable from deleting that tag and adding another, and `marker_label` falls back to
  the raw key so the trade still renders and stays editable.
- `management` accepts no new options — the review chain branches on exactly two states. Its labels
  are editable.
- Review-marker rows cannot be dragged to reorder, though the section copy says tags can be
  reordered. Order round-trips correctly; it just cannot be changed from the UI.

## Testing

325 tests pass. The three touched templates pass `node --check`.
