# Visual verification checklist — needs a human at a browser

No subagent in this run could perform these; every implementer disclosed them as skipped rather
than claiming them. All Python-side behaviour is covered by the test suite. Start with
`python3 server.py`, then work through in this order — later items depend on earlier ones.

## A. Trade V2 → ENTRY tab
1. LONG / MES, Price `7715`, Qty `3`, Stop `7688.50`. Risk reads `$398` with **no** R suffix.
2. Type Target `7760`. Risk becomes `$398 · 1.7R`.
3. Change Target to `7700` (below entry on a long — a typo). The R suffix **disappears** rather
   than showing a negative.
4. Clear Target. Suffix stays gone; readout matches step 1.
5. Press ENTER. Trade opens normally.

## B. Trade V2 → MANAGE tab (ledger)
6. A `Target` column sits between Stop and Risk, and **every column after it stays aligned with
   its header** — this is the single most likely visual defect, since it required adding a grid
   track to two selectors that must stay identical.
7. The OPEN row shows your target with a mint check; a blank one shows an amber dot.
8. Edit a target in its cell and tab out — the value persists after the row refreshes.
9. Footer reads `Idea Risk $398 · core $398 · add $0 · target $675 · 1.7R`.
10. Add a second entry with **no** target — footer gains an amber `1 entry with no planned exit`.
11. Add one with a wrong-side target — footer gains an amber `1 target on the wrong side of entry`
    and the aggregate R does **not** move (this was a fix round; worth confirming).
12. Exit part of the trade, return to MANAGE: Target cells become **static text with a lock icon**,
    no longer inputs.

## C. Day page → PLAN CHECK strip
13. The strip appears above the grade tray with an accurate outstanding count.
14. The hint reads `best price from entry through exit + 30 min`.
15. Click `before exit` with **no** price typed — red `enter a price first`, nothing saved.
16. Type a peak, click `before exit` — button highlights, row shows `saved`, input disables.
17. Reload — that trade is gone from the strip and the count dropped by one.
18. The `from earlier days` group renders with the date prefixed on each row.
19. Expand a trade tray and confirm the Exit tag group now offers the eight tags, with any
    existing selection still highlighted. **Check specifically that your 5 trades tagged
    `Bailed out - Reasses` still carry that tag** — the migration is append-only by design, but
    this is worth seeing with your own eyes.

## D. Weekly review → Plan vs Execution
20. Section renders below the Trade ledger with the bucket tiles.
21. Coverage line reads `Peak recorded on N of M trades.`
22. On a week with **no** peaks recorded, verdict tiles and headline are **absent** — not zeros.
23. Record a peak via PLAN CHECK, reload — the verdict band appears, coverage increments, that
    row shows a verdict chip.
24. A week with no trades at all shows `No trades this week.` without error.
25. Open a **pre-feature** week: it should render with `No plan` counts, em-dashes in the Peak
    column, and no crash.

## E. Theme check (known gap)
26. The new surfaces hardcode palette colors instead of using theme variables. On the light
    "paper" theme the mint `#4fffb0` markers are close to illegible. Parked, not fixed — worth
    seeing so you can decide whether it matters to you.
