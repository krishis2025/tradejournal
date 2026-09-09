# Session handoff

**Status as of 2026-09-08: the A/B/C grading feature is complete.** Nothing is in progress.

Earlier revisions of this file described mid-flight work with uncommitted changes. That state is
gone — the working tree is clean and every task is committed.

## What shipped

| Version | Change |
|---|---|
| 4.8.0 | Planned-exit (target) capture + the weekly Plan-vs-Execution report |
| 4.8.1 | Fix: deleting a tag no longer relabels the trades that used it |
| 4.8.2 | Fix: weighted `avg_entry` on multi-entry trades; asymmetric capture bounds |
| 4.8.3 | PLAN CHECK floored to trades traded under planned-exit capture |
| 4.9.0 | **A/B/C game grading** replaces the 5-point execution score, plus five diagnostic fields |
| 4.9.1 | `management_driver` on the review chain; "Did you break a rule?" → "Process violation" |
| 4.9.2 | Entry form: Qty above Price, cursor lands in Qty |

## Where to look

- **Spec:** `docs/superpowers/specs/2026-09-07-abc-grading-design.md`
- **Plan:** `docs/superpowers/plans/2026-09-07-abc-grading.md`
- **What still needs human eyes:** `docs/superpowers/handoff/2026-09-08-abc-grading-visual-checklist.md`
  — 28 UI checks no agent could perform, plus three parked cosmetic issues
- **Older follow-ups still open:** `docs/superpowers/handoff/2026-09-06-planned-exit-followups.md`
  — chiefly that a saved peak price cannot be corrected from the UI

## On first app start after pulling

Two one-shot guarded migrations run automatically, because `data/journal.db` is gitignored and
never travels with the code:

1. The seven assessment columns (plus `management_driver`) are added to `trades` and `live_trades`.
2. The retired `exit` tag vocabulary is deleted from `tag_config`. **`trade_tags` is untouched** —
   trades already tagged `Fear / Anxious`, `Planned — Monitored Continuation` or
   `Bailed out - Reasses` keep those tags.

## Testing

200 tests pass. No JavaScript test infrastructure exists, so the four UI surfaces rely on the
visual checklist above.
