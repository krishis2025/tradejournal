# Configurable Review Markers — design

**Status:** approved in brainstorming, not yet implemented
**Surfaces:** Settings → Tags → **Review Markers** (new, second tab); the trade review chain in
`live_v2.html`; the entry emotion question

## Purpose

Five vocabularies in the trade review are hardcoded Python tuples. They become editable the way
Technicals and Volume already are, and two of them — emotions and process violations — become
multi-select, because a trade is rarely one feeling or one mistake.

## The five groups

| Group | Question | Select | Notes |
|---|---|---|---|
| `management` | How did you manage it? | single | **Relabel-only** — see below |
| `management_issue` | What changed? | single | `none` locked |
| `management_driver` | What primarily drove your management decisions? | single | fully editable |
| `emotion` | What were you feeling? | **multi** | per-tag `at_entry` flag |
| `process_violation` | Process violation | **multi** | `none` locked |

The A/B/C grade is **not** in scope. It is a three-state judgement the whole framework is built on,
not a vocabulary.

**`management` is honestly relabel-only.** The code branches on exactly two states — "deviated" is
what makes the *What changed?* follow-up appear. You can rename both options; you cannot add a
third, because nothing would know what to do with it. Calling it "configurable" without this caveat
would be a lie the UI tells.

## Keys and labels

Every tag in these groups carries a **stable key** the code references and an **editable label**
the UI shows:

```
key: fear_of_loss          label: "Fear of loss"
key: traded_outside_plan   label: "Traded outside plan"
```

Trades store the key. Three things follow:

1. **Renaming is free.** Relabel "None" to "Clean" and every stored trade, every validation rule
   and every analytic keeps working. No cascade, no migration.
2. **Locked means undeletable, not frozen.** A locked tag can still be renamed — only its key is
   load-bearing. This is strictly better than freezing the row.
3. **The 4.8.1 class of bug cannot recur here.** That bug came from `save_tag_config` treating a
   deletion as a rename because labels were identity. Keys remove the ambiguity.

Today the review chain *derives* its labels from the slug (`value.replace(/_/g,' ')` plus a
special-case map for `market_thesis` and `pnl`). That derivation goes away — labels come from config.

**Locked keys:** `management.followed`, `management.deviated`, `management_issue.none`,
`process_violation.none`. Everything else is freely addable and deletable.

Locking is per tag and blocks deletion only. Blocking *addition* is a separate, group-level
property — `fixed_set` — set on `management` alone. Without it, locking both of management's
options would still leave an "+ Add new tag" box that produces a third state nothing can read.

## Multi-select

**The existing Multi-select toggle in Settings does not work.** Clicking it flips the switch and
marks the card dirty; pressing SAVE reports "✓ Saved"; the flag is never sent (`saveGroup` posts
`{ tags }` only) and never stored. On reload the card re-renders from the hardcoded `multi` value in
`app_logic.TAG_GROUPS`. Technicals is multi-select because the constant says so.

This work makes the flag real and persisted, for the existing groups as well as the new ones —
otherwise the toggle on the two new sections would be decorative in the same way.

Per-group storage goes in `app_config` under `tag_multi:<group_id>`, falling back to a default when
unset, so current behaviour is unchanged until the toggle is used. For the four existing groups the
default is the current `TAG_GROUPS` constant. The five new groups have no constant to inherit, so
their defaults are declared explicitly: `emotion` and `process_violation` multi; `management`,
`management_issue` and `management_driver` single.

**`none` is exclusive.** In a multi-select group, choosing the `none` key clears the others and
choosing any other clears `none`. "None plus Overtraded" is not a state worth recording.

## Storage on a trade

`emotion` and `process_violation` become **JSON arrays of keys** in their existing TEXT columns —
`["greed","impatience"]` — matching `sectors_json` and `tags_json`. No new columns, no new tables.

A one-shot guarded migration wraps existing scalars: `'greed'` → `'["greed"]'`, `''` and NULL left
alone. Eleven rows in the real journal at the time of writing (6 emotions, 5 violations), so the
cost is trivial and the risk is low.

Readers that change:
- `build_grade_analytics` counts `bc_emotions[r["emotion"]]` — becomes a count across the list.
- `weekly_review.html` renders `top_emotion[0].replace('_',' ')` — becomes the configured label.
- `close_live_trade_to_journal` copies the field through; it stays a pass-through.

`emotion_entry` stays **single-select**. It asks what you felt at one moment before entry, not
across a whole trade. It shares the `emotion` vocabulary but not its multi-ness.

## Entry emotions

The current rule is hardcoded by name: `ENTRY_EMOTIONS` is `EMOTIONS` minus `fear_of_loss` and
`fear_of_giving_back`, because you cannot feel either before you hold a position.

That becomes a per-tag **`at_entry`** flag, shown as a checkbox in the Settings card. The two fear
states ship with it off; anything you add defaults to on. Explicit, survives renames, and decided
per emotion rather than inferred.

## Validation

`_ASSESSMENT_VOCAB` reads the configured vocabulary at request time instead of closing over module
constants. Two consequences:

- An unknown value is still rejected — the vocabulary is closed, it is just no longer fixed at
  import.
- The A-grade rule becomes "no violation whose key is other than `none`", evaluated against the
  list. It survives relabelling, and with multi-select it means *any* non-`none` entry conflicts
  with an A.

`server.py`'s entry-emotion check (`emotion_entry must be one of …`) reads the `at_entry` set.

## Settings UI

A new **Review Markers** sub-tab, placed **second**, between Technical Markers and Observation
Markers. Same card UI, same editor, same save path as the existing tag cards, plus:

- a lock indicator on locked rows, with the delete control removed (the text input stays editable)
- an `at_entry` checkbox per row, on the emotion card only
- a Multi-select toggle that now persists

## Testing

- Keys survive relabelling: rename a tag, assert stored trades and validation are unaffected.
- A locked tag cannot be deleted; a locked tag CAN be renamed.
- Deleting a tag does not relabel trades that used it (the 4.8.1 guard, re-pinned for keys).
- `none` exclusivity in both directions.
- Multi-value round trip through the API and back onto the board of the review page.
- The scalar → JSON-array migration, run twice, over rows that are already arrays.
- Analytics count emotions across a list, not as a scalar.
- The multi flag persists and is honoured — including for a pre-existing group.
- An unknown key is still rejected after the vocabulary moves to config.
- `at_entry` drives the entry question, including for a newly added emotion.

No JavaScript test infrastructure exists. The Settings card interactions, the multi-select chip
behaviour and the lock affordance need human verification.

## Not building

- The grade vocabulary stays fixed.
- No third `management` state.
- No reordering of the review questions themselves — only their options.
- No per-account vocabularies; config stays global, as tags are today.
- No backfill UI for re-tagging historical trades against a changed vocabulary.
