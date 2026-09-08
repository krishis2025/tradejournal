# Visual checklist — A/B/C grading (v4.9.0)

No agent in this run could open a browser. Everything computational is covered by 185 tests; these
are the parts only you can judge. **Start the app once first** — that triggers two one-shot
migrations (the seven assessment columns, and deleting the retired `exit` vocabulary).

## A. Assessment page (Trade V2, before entry)
1. The first tile reads **Trade came to me** / *I waited for my level.* — same look as before.
2. `0 / 3 process · 0 / 4 technical` still counts up as you tick tiles.
3. The old **CALM / FOMO** pair is replaced by six emotions; no fear options (they need an open position).
4. **CONFIDENCE** is unchanged.
5. **Setup** and **Pre-trade** pickers appear in the right panel and hold a selection.
6. Tick *Trade came to me* → the matching Pre-trade tag selects itself. Untick → it clears.
7. **Enter a second trade in the same session.** The tiles must start **unticked** and the tag
   panel empty. (This was a real bug found in final review — from trade 2 the tile stayed ticked,
   so the tag was never set.)

## B. Review page (after closing a trade)
8. The `n/5` execution score and both old question blocks are gone.
9. Three grade cards with the full A/B/C definitions and the *P&L has no vote* line.
10. **Followed process** → no *What changed?* block. **Deviated** → it appears.
11. Grade **A** → no *Did you break a rule?* block. **B** or **C** → it appears.
12. Set B + a violation, then switch to **A** — the block disappears and the value clears rather
    than erroring.
13. Switch **Deviated → Followed process** after picking an issue — no error.
14. Entry recap, notes and the right panel are unchanged.

## C. Day page
15. Graded trades show a coloured letter chip; ungraded show none.
16. The **pre-trade tag panel** still renders in its own three-column block with green/red
    good-vs-bad colouring. (This broke silently once — it is now covered by a test, but worth a look.)
17. The day grade percentage still renders.

## D. Weekly review
18. Three A/B/C cards replace *Avg Exec Score*, with `Graded N of M trades` beneath.
19. Table shows `Grade`, a **coloured** `Capture`, and `P&L`; no `Verdict` column.
20. A losing trade shows `—` for Capture and a red P&L.
21. Capture colours: `<0.60` red, `0.60–0.80` orange, `0.80–1.10` green, `>1.10` blue.
22. The `Targets: N too far · N well calibrated · N too close` line appears when trades have both
    a target and a peak.
23. The B/C diagnosis line appears only when the week has a B or C trade.
24. No fear/greed headline, no verdict tiles, and **no "Planned vs Fear" card** (retired).
25. Open a **pre-feature** week — renders with `Graded 0 of N` and no errors.

## E. Known cosmetic issues — parked, tell me if they bother you
26. The Behaviour card grid is a fixed 4-column layout now holding **5** cards, so the last row is
    an orphaned single card. Purely visual.
27. The weekly `Grade` cell uses the old verdict pill styling, so A/B/C all render the same grey —
    unlike the day page, which colours them.
28. The day page still shows the retired `n/5` badge alongside the new grade chip.
