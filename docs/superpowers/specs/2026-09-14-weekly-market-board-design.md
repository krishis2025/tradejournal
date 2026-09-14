# Weekly Market Board — design

**Status:** approved in brainstorming, not yet implemented
**Surface:** the weekly review page (`/weekly-review`), week-scoped like everything else there

## Purpose

A market board you read for two jobs, both forward-looking:

1. **Orient before trading.** Glance at Tuesday morning to know what regime the week is in.
2. **Prepare for the coming week.** Read the finished board on Sunday to see how sectors
   behaved, and plan against it.

Both are the same board viewed for different weeks, so it travels with the week the page is
already showing. There is no separate "last week" view to build.

Because a finished week is re-read later as a record, whatever is typed last before Friday's
close *is* the historical figure. There is no close event and nothing locks. This is accepted,
not an oversight.

## Instruments

Twenty, in fixed order. Order never changes between visits — stable positions were chosen
deliberately over performance ranking, so the board can be read from muscle memory.

| Group | Instruments |
|---|---|
| Indices (3) | S&P 500 (SPX cash), Nasdaq 100 (NDX cash), Russell 2000 (RUT cash) |
| Sectors (12) | Tech XLK, **SMH**, Fin XLF, Comm XLC, Disc XLY, Indust XLI, Health XLV, Staples XLP, Energy XLE, Utils XLU, Matls XLB, RE XLRE |
| Macro (5) | BONDS (TLT), 10YR YIELD (TNX), VIX, GOLD (/GC), OIL (/CL) |

Notes:

- **Cash indices, not futures.** The board says S&P 500 and the number entered is SPX. This
  costs a lookup — futures are what's already on screen — and buys a record that still means
  what it says months later.
- **SMH is not a GICS sector.** It sits in the sectors group by request, directly after Tech.
  The group heading stays SECTORS.
- **This list is independent of the daily sector vocabulary in internals.** SMH is *not* added
  there. The two surfaces share tickers by coincidence, not by contract.
- Twenty instruments means twenty values typed on Monday and twenty retyped per refresh. The
  entry burden was the explicit tradeoff and was accepted.

## Data model

One row per instrument per week:

```sql
CREATE TABLE IF NOT EXISTS weekly_market_prices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
    week_start  TEXT NOT NULL,              -- Monday, ISO
    instrument  TEXT NOT NULL,              -- stable key: 'XLK', 'SPX', 'TLT', ...
    monday_open REAL,                       -- NULL until entered
    current     REAL,                       -- NULL until entered
    updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(account_id, week_start, instrument)
)
```

`REAL`, not `TEXT`. `market_internals` stores `TEXT` because those are free-form readings; these
are prices, and `trades`/`fills` already store prices as `REAL`.

`instrument` holds a stable key, never the display label. Labels live in the code constant, so
renaming "BONDS" to "TLT" on screen never orphans a row.

**Nothing derived is stored.** The percent is computed on read, like every other ratio in this
app.

**Input coercion at the API boundary.** `7,656.98` will get typed. One parser strips commas and
stray characters and rejects what isn't a number; the database never sees a string.

## Percent

```
pct = (current - monday_open) / monday_open * 100
```

`None` — rendering `—` — when either value is missing or `monday_open` is zero. The zero case is
not theoretical: a blank open is the normal state of every instrument at the start of a week, and
dividing by it is the first thing that would break.

Yields need no special case. 4.61 → 4.79 is +3.97%, which is what the reference board shows.

## Display

Four columns, the screenshot's structure at the screenshot's scale, in the app's dark palette and
fonts. Icons are inline SVG, monoline, matching the existing internals icons — not emoji.

```
INDICES        SECTORS                      MACRO
S&P 500        Tech       Staples           BONDS
  7,656.98       +0.51%     (1.07%)           80.87
  (0.79%)                                     (1.90%)
Nasdaq 100     SMH        Energy            10YR YIELD
  29,368.44      +1.42%     +0.48%            4.79
  (0.93%)                                     +3.97%
Russell 2000   Fin        Utils             VIX
  2,903.95       (0.80%)    (1.53%)           15.56
  (1.21%)                                     +1.80%
               Comm       Matls             GOLD
                 +0.91%     (2.69%)           4,392.80
                                              (1.65%)
               Disc       RE                OIL
                 (1.32%)    (0.57%)           100.24
                                              +7.83%
               Indust
                 (1.58%)
```

Indices and macro show **price and percent**; sectors show **percent only**. That is the
screenshot's own split — things with a level, versus things with a move.

Collapses to two columns, then one, on narrow screens. Sectors occupy two columns of six.

### Colour

**Green for up, red for down, for every instrument** — including VIX, 10YR and OIL, where a rise
is bearish for equities.

This deliberately differs from the internals delta pills shipped in 4.10.0, where those same
three go dark red on a rise. It is not an inconsistency to be fixed. The two surfaces have
different jobs:

- **Internals is a signal surface.** It says what a move *means for your bias*, so red means
  bearish.
- **The weekly board is a market surface.** It says what *moved*, so green means up.

Anyone tempted to align them should change neither.

Negatives render parenthesised, positives with an explicit `+` — the accounting convention the
reference board uses, and the reason it reads quickly.

## Entry

An `Edit values` control unfolds a table inline on the weekly page: Instrument | Mon open |
Current. Twenty rows. Autosaves on blur, as internals does.

**Every cell is a real `<input>` and Tab runs across a row** — open, then current, then into the
next instrument. This is the 4.10.0 lesson applied at build time rather than retrofitted: a cell
that hides its input behind a click is a cell Tab skips, and a grid that needs the mouse does not
get filled.

Monday's open is typed once and then left alone. A mid-week refresh means tabbing down the
Current column only.

## Empty and partial states

- **Unfilled week:** all twenty instruments render with their names and `—`. The board never
  hides itself. A panel that vanishes when empty is a panel that gets forgotten.
- **Open entered, current blank:** the open shows as the value, the percent shows `—`.
- **Instrument later removed from the list:** its historical rows remain in the table and stop
  rendering. Recoverable, not lossy. Preferred over deleting history.

## Testing

- Percent maths, including the zero-open and missing-value paths.
- All twenty render in fixed order against an empty table.
- A negative renders parenthesised and red; a positive signed and green.
- Comma-tolerant round-trip through the API (`7,656.98` → `7656.98`).
- Week isolation: writing this week must not touch last week's row for the same instrument.
- Account scoping.

No JavaScript test infrastructure exists in this repo. Colour, layout, icon rendering and the
actual Tab path need human verification.

## Not building

Each of these was a live option and was closed:

- **No price auto-fetch.** This app journals after the fact and has no market feed. Adding one is
  a different project.
- **No per-day history.** One mutable `current` per instrument per week.
- **No performance sorting.** Fixed order was chosen over leaders-at-top.
- **No last-week column.** Comparison is done by navigating weeks.
- **No configurable instrument list.** The twenty are a code constant.
