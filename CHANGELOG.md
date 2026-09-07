# Changelog

All notable changes to Trade Journal are documented here.

## [4.8.0] — 2026-09-06

### Planned exit capture & Plan-vs-Execution review

Records what was planned, not just what happened, so the weekly review can separate a
disciplined exit from a fearful one.

- **Planned exit per entry decision:** a Target field on the Entry and Add forms and a Target
  column in the Manage ledger, stored alongside the existing per-tranche stop and carried onto
  journal fills on push. Blank is a recorded state (`'none'`) — there is no default target.
- **Frozen at first exit:** targets stop being editable once a trade has any exit, enforced
  server-side with a 409. A target is a record of intent, so editing it after the outcome is
  known would let the review confirm itself.
- **Peak price capture:** a PLAN CHECK strip on the day page records the best price the market
  offered around each trade, plus whether that peak came before or after the exit. Push
  behaviour is unchanged.
- **Plan vs Execution section** on the weekly review: capture % against the plan, bucketed
  (Stopped / Cut early / At plan / Ran past) with a configurable band, and — where a peak was
  recorded — the three-way split of Cut early into froze at target, bailed early, or the market
  never paid. Also reports give-back, missed run, and target realism.
- **Coverage is always shown.** Peak-derived percentages cover only the trades with a recorded
  peak, and the section says so rather than implying they cover the week.
- **Widened exit tag vocabulary:** Target hit, Target never reached, Stopped out,
  Greed / chased, Time stop, Management error.
- **Test suite introduced.** The project previously had none; pytest now covers the schema,
  routes, freeze rule, and all plan-vs-execution derivation.

## [4.7.0] — 2026-07-23

### Market State hero badge → two-part banner (Trade V2)

Moved the Market State hero badge into the top banner and made the banner two-part on every tab.

- **Two-part banner:** hero badge (left) · vertical divider · playbook headline (right). The trade
  plan legs were removed from the banner (they live in the Trade Plan panel) — playbook headline
  only. Playbook recolored gold → steel blue (`#7fa8d4`; `#3d648f` on light themes).
- **Badge is one shared view:** a single `msBadgeHtml()` builder feeds both the Context strip and
  the banner from the shared `msState`; a factor tap re-renders all visible badges (`msSyncViews`
  now also refreshes the banner) so they never disagree. No new state, no new recompute path.
- **Banner goes dark** (`--banner-bg #101319`, border `#1e222b`, divider `#262b35`) so the badge's
  green/red/slate read as designed; all via CSS custom properties. Light themes keep a light banner
  with the badge darkened for contrast (green `#1f5138`, red `#7a3540`, slate `#4a5262`, ⚠ `#8a5a1f`,
  ⇅ `#7a3540`, reason `#6a6a5a`) — the CORE ALIGNED green-headline vs slate-headline distinction
  survives on both themes.
- **Rail badge removed:** the Entry/Manage vertical rail now shows the four factors only (ADH,
  Tech·XLK, Value, Sectors); it's shorter, so Session and Open Trades move up.
- The badge also stays in the Context center-panel strip (unchanged) — on Context it shows in both
  the strip and the banner, intentionally.

## [4.6.0] — 2026-07-20

### Market State: vertical rail + unbundled auto-save (Trade V2)

Relocated the Market State into a persistent, always-editable **vertical rail** in the left
panel and split its save model from the Context form. The factor/badge/color design is unchanged
— this is relocation + a save-model change. Restore point: tag `market-state-center-panel-v1`.

- **Unbundled auto-save:** market state (ADH / Tech / Value / Sectors) now persists on **every
  tap** via auto-save. **"Update Context & Plan" no longer writes market state** — it saves only
  the form fields (Day Type, Volume, HTF Trend, Headline Read, Playbook, Signals). Pressing Update
  after changing market state no longer reverts it; auto-save owns market state exclusively.
- **Vertical rail** (`msRailInner`) on **Entry and Manage** left panels: badge on top, then ADH ·
  Tech · Value · Sectors stacked, each editable inline. It and the horizontal Context strip are
  **two views of one `msState`** — a tap on either re-renders both and recomputes the badge
  identically (`msSyncViews`). On **Context** the rail is hidden (the horizontal strip is the
  surface there); left panel is Session → Open Trades.
- **One-source-of-truth fixes:** `msPersist` now keeps the in-memory context caches
  (`lastCommittedContext` / `SERVER_CONTEXTS`) in lockstep with taps, so tab switches no longer
  revert to stale state; `renderAll` seeds `msState` from the active context **before** any view
  paints (`msSeedFromActive`), so the rail/strip never disagree on load.
- Removed the unused "+ Create New Context" button (update-in-place model). The Headline Read
  lives only in its form tile, now a ~4-line auto-scrolling textarea. `startNewContext()` is left
  in place but is now unreferenced (flagged; backend create path still used by first-time commit).

## [4.5.1] — 2026-07-20

- Strength indicator on ADH/Tech: replaced the continuous fill-bar with a segmented 3-cell bar
  (weak=1 / moderate=2 / strong=3 cells filled). Rendering-only.

## [4.5.0] — 2026-07-19

### Context "Market State" strip + trade-state capture

Redesigned the Context tab's market read into a compact **Market State strip** (ADH, Tech·XLK,
Value, Sectors + a computed alignment badge) on Trade V2, and stamped that read onto each trade
at entry for later review. The live strip, its badge logic, and colors are shared via page-local
CSS custom properties (dark + Paper-Light).

**Market State strip (Context tab):**
- **ADH & Tech·XLK** share one control: **Zone** (−ve / coiling / +ve) + **Strength**
  (weak / moderate / strong). Strength renders as a single continuous **fill-bar** (⅓/⅔/full) in
  the factor's direction color over a dim track; coiling shows no bar. Strength is **display-only** —
  it never feeds the sizing/verdict.
- **Sectors** uses the same grammar: **Zone** (−ve / rotational / +ve) + **Breadth** (Heavy / All);
  rotational is static (no pulse) and disables breadth.
- **Badge** is **descriptive, not prescriptive** — no multipliers. Core-first, direction-agnostic
  (long/short mirror): `FULL ALIGNMENT · TREND DAY`, `STRONG ALIGNMENT`, `CORE ALIGNED` (forest-green
  when sectors rotational ⚠, slate when sectors opposite ⇅), or `MIXED`. The two CORE ALIGNED states
  share words and differ only by headline color.
- Fixed a persistence bug (ADH/Tech/Sectors taps lost on "Update Context & Plan") and a layout bug
  (the "strong" strength chip was unclickable when the row overflowed its column).

**Trade-state capture (review):**
- At the entry fill, the strip is frozen into an immutable `market_state_json` snapshot (full factors
  + strength + badge) on the trade — a photograph, not a live link. Changing the live strip afterward
  never alters an entered trade's snapshot.
- The snapshot lives on both `live_trades` and `trades` and **survives the push-to-journal**. The
  trade detail view reconstructs the captured badge from the stored blob; trades with no snapshot show
  "No market state captured".
- Group-by-regime P&L analytics are deferred to a later pass (data captured now).

**Schema (additive, guarded migrations):**
- `developing_context`: `ms_adh_zone`, `ms_adh_strength` (renamed from `ms_adh_trend`), `ms_tech_zone`
  (from `ms_tech_dir`), `ms_tech_strength` (from `ms_tech_mom`), `ms_sectors_zone`, `ms_sectors_breadth`
  (legacy `ms_sectors` retained, best-effort backfilled).
- `live_trades` and `trades`: `market_state_json` (nullable). Existing rows unaffected.

## [4.4.1] — 2026-07-03

### Retire the old Live Trade (Ticket) and Legacy View UIs

Removed two unused live-trade UI layers now that **Trade V2** (`/live-v2`) is the sole
live workflow. Done in stages: hidden from nav first, then deleted after confirming the
shared/exclusive split.

- **Deleted (exclusively reachable from the retired views):** templates
  `live_ticket.html` (Ticket UI, renamed to `legacy_trade_exe.html` before deletion),
  `live_list_legacy.html`, `live_entry_legacy.html`; routes `/live` (`live_trade_page`),
  `/live-legacy`, `/live-legacy/new`, `/live-legacy/<id>`.
- **Untouched (shared with Trade V2 and/or the journal):** the entire `/api/live/*`
  API, all live-trade backend (`close_live_trade_to_journal`, `recalculate_live_trade`,
  `compute_live_trade_plan`, `get_all_live_trades`, `INSTRUMENT_CONFIG`, risk math, …),
  `/api/session/summary`, and the `live_trades` / `live_trade_levels` /
  `live_trade_executions` / `live_trade_images` tables. **No database changes** — all
  existing live-trade data is preserved.
- Trade V2, the journal, and Weekly Review verified working after the removal.

## [4.4.0] — 2026-06-30

### Trajectory cockpit — frequency-first verdicts, focus

Replaces the 2+2 trajectory zone with an all-detectors cockpit: every tracked
detector as a tile with a frequency trend, a computed verdict, and a dollar readout.

- **Schema (additive, guarded):** `weekly_meta` (per-week `total_trades` + `qualifying`),
  written by the weekly hook so behavior **frequency** = `count / total_trades` is
  computable. `SCHEMA.md` updated.
- **Frequency-first verdict engine (pure Python):** per detector over the trailing 8
  qualifying weeks, the verdict is driven **solely by frequency %** (first-4 vs last-4,
  trend only when |Δ| *exceeds* `FREQ_DEADBAND`) — frequency is size/luck/account-proof
  and needs no stop data. Leak: down → Improving, up → Worsening, within band → Holding
  steady; strength (`came_to_me`) inverts (up → Building, down → Slipping). Severity
  ($/occurrence) is demoted to a title-line **"⚠ costlier each time"** flag (fires when
  frequency isn't worsening but per-occurrence cost rose beyond `SEVERITY_DEADBAND`).
  A single week > `OUTLIER_SD` (2.0) SDs from the window mean *in the bad direction*
  raises a **"⚠ Week N spiked/dipped"** flag (good-direction outliers are never flagged);
  this replaces the old relapse flag. Generated frequency-led verdict sentence.
- **Windows:** verdict = 8 qualifying weeks (4-vs-4), so a verdict needs **8** qualifying
  weeks of history (`MIN_QUALIFYING_FOR_TREND`); below that the tile shows
  "Not enough data — N of 8 weeks". Sparkline display = 12 weeks. All rolling, configurable.
- **Single badge:** the verdict is the only badge (the earlier subordinate recency-state
  badge was dropped to keep the title line unambiguous).
- **Cockpit UI:** Strengths section first, then Leaks (focused pinned → active by
  urgency → collapsed "quiet" strip of non-firing detectors). Each tile: verdict badge
  (+ relapse + recency), frequency sparkline, verdict sentence, and dollar readout
  (`this wk` headline + `8-wk avg`; `—` when the current week is non-qualifying). No cap
  on active tiles.
- **Focus = intention:** tapping a tile's focus toggle creates/deletes a targeted
  intention (`weekly_intentions.targets`); max 2 enforced (a 3rd is blocked, not bumped).
  New `POST/DELETE /api/weekly-focus`; new `db.delete_weekly_intention`,
  `db.get_focus_targets`, `db.upsert_weekly_meta`, `db.get_weekly_meta_map`.
- **Settings:** verdict window, sparkline window, focus max (+ existing floor/thresholds)
  via the config endpoint. Deadband/material thresholds are code constants, tunable.
- **Trajectory gear panel (per-account):** a ⚙ settings panel on the cockpit exposing
  **Qualifying floor** and **Focus max** (everyday) plus **Frequency deadband** and
  **Severity deadband** under an "Advanced — these change how trends are judged" section
  with a caution note. Each field has an always-visible plain-language helper; the
  deadband fields show this window's live movement for the reference detector
  ("impulsive frequency moved 4 pts", "severity moved $53"). Persisted per-account in
  `account_config` (`traj_*` keys), with a **Reset to defaults** button. New
  `POST /api/trajectory-settings` (+ `{reset:true}`); getters are account-aware and
  fall back to code defaults. Other constants (chronic %, relapse multiplier, windows,
  recurrence) stay in code.

## [4.3.0] — 2026-06-29

### Trajectory tracking + intention linkage

Turns the Weekly Review from a mirror (this week's insights) into a coach (your
trajectory): which leaks you're repeating, which you're improving/have beaten, and
whether the intentions you set are actually working — over a rolling multi-week
window. Deterministic, local, built on the existing story-engine detectors.

- **Detector ID rename** (one canonical spelling everywhere, no aliases): story-engine
  keys now match the trajectory spec — `impulse_bucket`→`impulsive_bucket`,
  `operational`→`operational_error`, `outlier_loss`→`oversized_loss`,
  `exit_discipline`→`weak_exits`, `expectancy`→`expectancy_gap`,
  `sign_flip`→`concentration`. No persisted data existed under the old keys.
- **Schema (additive, guarded):** `insight_log` (one row per tracked detector per
  week: `fired`, signed `magnitude`, `count`, `qualifying`,
  `UNIQUE(account_id, week_start, detector_id)`); `targets` column on
  `weekly_intentions`. `SCHEMA.md` updated.
- **Detector registry** (`DETECTOR_REGISTRY`): single source of truth — id →
  `{label, polarity, tracked}`. 8 tracked patterns (7 leaks + `came_to_me` strength);
  `net_result`/`concentration` not tracked.
- **Weekly logging hook:** `persist_insight_log` / `log_week_insights` — `fired`
  reused from the detectors, `magnitude`/`count` from the canonical summary,
  `qualifying = 1` when the week met the trade floor (default 5). Idempotent upsert,
  wired into `build_weekly_review_data`; backfills trailing history from existing
  trades so trajectory works on day one. Zero-trade weeks aren't logged.
- **State classification:** New / Recurring / Chronic / Improving / Resolved over
  rolling windows of *qualifying weeks only* (recurrence 4, trend 8, chronic ≥60%,
  improving = magnitude slope over last ≥3 firings, resolved = 3 qualifying weeks
  silent). Precedence Resolved > Improving > Chronic > Recurring > New; suppressed
  below 4 qualifying weeks. Strength polarity flips ("improving" = magnitude up).
- **Intention linkage:** proposed rules auto-stamp their `targets` detector; self
  rules pick one from a dropdown. "Is it working?" reads the targeted detector's
  trajectory since the rule was set → working / mixed / not_working / too_soon;
  `targets=''` falls back to manual grading only.
- **Trajectory zone (Weekly Review page):** a band above Planning, shown only when
  viewing the most-recent week (anchored to a trailing window independent of the
  viewed week; hidden on past weeks). Two buckets — Repeating and Improving/beaten —
  capped at 2 rows each, with state badges, theme-adaptive magnitude sparklines,
  weeks-fired, latest value, and intention→pattern verdict cards. A faded strength
  reads as a warning, not a win. "Building — N of 4 weeks" placeholder before enough
  history. New tunables (recurrence/trend windows, chronic %, qualifying floor) via
  the weekly-review config endpoint.

## [4.2.0] — 2026-06-26

### Weekly Review dashboard + story engine (V1)

A weekend-friendly weekly review that reconstructs the week's story from structured
data already captured during trading — so it works even on weeks with no written
notes. New **Weekly** tab in the top nav.

- **Schema:** `weekly_reviews` and `weekly_intentions` tables; `theme` column on
  `observations` (additive, guarded migrations). Updated `SCHEMA.md`.
- **Data layer:** `get_trades_in_range`, `get_or_create_weekly_review`,
  `update_weekly_review`, `add_weekly_intention`, `set_intention_result`,
  `get_weekly_intentions`, `get_observations_in_range`, `get_theme_counts`.
- **Story engine (`app_logic.py`):** deterministic, local, no model/network. 10
  detectors (net result, operational separation, impulsive bucket, revenge-after-loss
  chain, outlier loss, sign-flip concentration, expectancy, exit discipline,
  no-setup leak, came-to-me payoff) → an assembler that leads with the net result,
  pins operational separation to slot 2, then ranks the rest by absolute dollar
  impact (max 4 sentences). Same input → same output. `propose_intentions()` maps
  fired detectors → candidate rules. Tunable config (`IMPULSE_TAGS`,
  `OPERATIONAL_TAGS`, `OUTLIER_LOSS_MULT`, `MATERIAL_USD`, `STORY_MAX_SENTENCES`);
  tag lists editable via `app_config`.
- **Zones:** header KPIs (Net / Discretionary / Operational split, win rate, trades,
  days), the story paragraph, behavior & process (came-to-me vs impulsive, avg exec
  score, exit discipline, setup table, trade ledger with operational/revenge flags),
  lessons (observation filmstrip, review notes & day reflections, recurring-theme
  counts), and the planning loop (grade last week's intentions, accept proposed
  rules, add your own, weekly reflection).
- **Routes:** `GET /weekly-review`, `GET/POST /api/weekly-review`,
  `POST /api/weekly-intention`, `PATCH /api/weekly-intention/<id>`,
  `POST /api/weekly-review/config`.
- Discretionary stats everywhere exclude `Operational Error`-tagged trades and show
  the operational amount separately; the trade is never deleted.

Fast-follow (not in V1): equity-curve chart (zone 2) and risk/R visuals (zone 3,
which needs forward-captured stops).

## [4.1.0] — 2026-06-25

### Per-tranche stop & risk capture (Manage tab)

Capture the **intended stop price for each entry decision** (the OPEN and every ADD) so the journal can show, per trade idea, how much was risked — separate from the live working stop that drives the right-panel net-risk number. Risk is always derived on read; nothing computed is persisted.

- **Schema:** added nullable `stop_price` + `stop_source` (`'default'`/`'entered'`/`'edited'`) to both `fills` and `live_trade_executions` (additive, guarded migration). Updated `SCHEMA.md`.
- **Data layer:** `insert_fill` / `add_live_trade_execution` accept `stop_price`/`stop_source`; new `update_live_trade_execution_stop()`.
- **Logic:** `compute_default_risk_stop()` (direction-aware 20-pt default) and `compute_tranche_risk()` (`|exec − stop| × entry_qty × $/point`, using the row's full committed qty).
- **Routes:** `POST /api/live` and `POST /api/live/<id>/add` accept optional `stop_price` (else 20-pt default); new `PATCH /api/live/<id>/execution/<exec_id>/stop`.
- **Entry & Add forms:** Stop field (defaults to entry ∓20 pts) with a live risk readout.
- **Transactions ledger:** new **Stop** (editable on OPEN/ADD) and **Risk** (derived) columns. Captured stops show a mint check; 20-pt defaults show an amber dot + amber warning on the risk value. Footer strip: `IDEA RISK $X · core $Y · add $Z` with a discipline note when any stop is still on the 20-pt default.
- **Tap-to-pull:** per-row `pull` chip pulls a price from the working stops (single distinct price → tranche-open-qty match → picker), applied to the row's full entry qty and frozen as `'edited'`.
- **Carry-through:** push to journal copies each entry-side execution's `stop_price`/`stop_source` into `fills`; risk stays derivable journal-side.

## [4.0.5] — 2026-06-24

### Bug fixes

**Day view showed 0 trades (phantom NULL-account day)**
- Opening Market Internals for "today" created a `trading_days` row with `account_id = NULL` (and a
  lower id), so navigating to a date resolved to that empty row instead of the real account day holding
  the trade — the day view read "0 trades · +$0".
- Today-internals routes (`/api/today/internals` GET + POST) now resolve an account
  (`?account=` → primary account fallback) via the new `db.get_primary_account_id()` helper, so they
  upsert the real account day instead of a NULL one. `live_v2.html` passes the active nav account on
  these calls. (`internals_v2.html` is day-scoped and unaffected.)
- The calendar now navigates by day **id** (`calendar_data` carries `id`), and `/day/<date_str>` accepts
  `?account=` and resolves via `get_day_by_date_account()` with a legacy fallback — so clicks land on the
  correct account-scoped day.
- Added a one-time, idempotent cleanup migration that merges each phantom NULL-account day into the
  single account day for the same date (moves `market_internals` respecting `UNIQUE(day_id, session)`,
  moves `day_images`, backfills empty reflection fields), then deletes the NULL day only when nothing
  remains attached. Dates with zero or multiple account days are left untouched.

**Monthly Evaluation panel mixed all-time and month-scoped numbers**
- Total Trades, Winning/Losing Days, Trades/Day, and Trades/Week were computed from the full dataset
  while Best/Worst Day used the current month. The panel is now fully **month-scoped**; the top KPI cards
  remain scoped to the selected date-range preset.
- **Avg Hold Time** now shows real data: `get_all_days()` returns an average trade duration per day
  (handles both `HH:MM` and `HH:MM:SS` stored times, ignores cross-midnight artifacts); the panel
  averages it across the month weighted by trade count.

## [1.4.2] — 2026-03-08

### Sizing Cheat Sheet — Visual Polish
- Replaced colored background pill labels with **colored dot + text** for tier indicators (green/yellow/red)
- Dots are theme-adaptive: bright on dark themes, muted on Paper Light
- Consistent dot + label pattern used both in the streak summary bar and inside account tiles
- Renamed "Medium" tier to **Standard**
- Risk text format changed to `20pts stp — $100` for clarity
- Added **IBM Plex Sans** font for tier labels, streak summary, and risk text
- Removed emoji icons from tier labels

### Account Deletion — Cascade Delete
- Deleting an account now **permanently removes all associated data**: trading days, trades, fills, tags, live trades, and shadow trades
- Previously, deleting an account orphaned its data (set account_id to NULL)
- Updated delete confirmation message to warn about permanent data loss
- Added error handling to the delete account API endpoint

---

## [1.4.1] — 2026-03-08

### Sizing Cheat Sheet v2
- Redesigned sizing section with **tile-based layout** — one card per account
- Three statistical risk tiers: Conservative (99%), Standard (95%), Aggressive (80%)
- **Expected max losing streak** formula based on win rate, horizon (200 trades), and confidence level
- Per-account qty calculation: `floor(account_size / streak / cost_per_contract)`
- Interactive controls: instrument toggle (MES/ES), win rate input, stop loss slider (5–50 pts)
- **Inline account size editing** — click the dollar amount on any tile to override
- **Auto win rate** — pulls blended win rate from accounts with 60+ trades
- Streak summary bar showing expected max consecutive losses per tier
- Theme-adaptive color system with CSS custom properties for all 3 themes

---

## [1.4.0] — 2026-03-07

### Multi-Account Evolution
- Renamed Portfolio → Account throughout the application
- Account Mirror feature for shadow trade projections
- Simplified Simulation page layout

---

## [1.3.3] — 2026-03-07

### Trade Execution View
- Enhanced with scorecard and risk progression

---

## [1.3.2] — 2026-03-07

### Pre-Trade Risk Calculator
- Command bar UX improvements

---

## [1.3.1] — 2026-03-07

### Day View
- Moved notes to day view
- Removed tags/notes from trade execution view

---

## [1.3.0] — 2026-03-06

### Trade Notes — 3 Separate Fields
- **Entry or Rationale**: renamed from the single "Trade Notes" field — capture why you entered
- **Monitoring Continuation**: new field — track ongoing observations during the trade
- **Exit Notes**: new field — document exit reasoning and lessons learned
- All 3 fields are expandable (resize vertical), at least 5 rows each
- Auto-save with debounce (600ms live, 800ms journal)
- All 3 fields persist through "Save & Push to Journal" and display in trade detail view

### Live Trade — Time Input Improvements
- Widened time input box (70px → 110px) so full time is visible
- Added ↻ refresh button next to time field — one click sets current system time
- `PORT` environment variable support (`PORT=5050 python server.py`)

### Bug Fixes
- Fixed NULL total_pnl crash on dashboard when trading days have no trades (COALESCE fix)

### Database
- New `notes_monitoring` and `notes_exit` columns on `trades` and `live_trades` tables
- Auto-migration for existing databases

---

## [1.2.0] — 2026-02-28

### Analytics — Enhanced Dashboard
- **Date range filtering**: All Time, This Week, This Month, Last 30 Days, Last 90 Days presets + custom date picker
- All charts, KPIs, and tables respect the selected date range

### New KPIs
- Average Win / Average Loss with win-loss ratio
- Expectancy: (win_rate × avg_win) - (loss_rate × avg_loss)
- Profit Factor: gross profit / gross loss
- Average Trade Duration (entry to exit, in minutes)
- Trading Days count

### New Charts
- **Equity Curve**: cumulative P&L line chart across all trades with fill and per-trade tooltips
- **Drawdown Chart**: red filled area showing drawdown from equity peak, max drawdown in subtitle
- **Calendar Heatmap**: monthly grid with day cells colored by P&L intensity (green/red), hover tooltips
- **Trade Duration vs P&L**: scatter plot with wins (green), losses (red), breakeven (grey)

### Analytics Layout
- Organized into labeled sections: KPIs → Equity & Risk → Calendar → Time & Duration → Tag Analytics
- Best/Worst trade shown as compact inline cards
- Section dividers with headers for visual hierarchy

---

## [1.1.0] — 2026-02-28

### Live Trade — Multiple Simultaneous Trades
- Open and manage multiple live trades at the same time
- Color-coded trade cards (6 distinct colors) with numbered banners (T1, T2, T3…)
- Tabbed right panel — each open trade gets its own tab with color dot indicator
- Active trade banner showing trade number, direction, instrument, and entry details
- Active card glow effect on left panel; inactive cards dimmed for focus
- Flash animation on trade switch for clear visual feedback
- New trade opens without interrupting current active trade (toast notification instead)

### Trade Detail — Execution Replay
- Pushed live trades now store full execution detail (levels + executions) as JSON
- Trade detail page shows execution breakdown with entry/exit types (TP hit, stop hit, manual exit)
- Fills table now includes `exit_type` column for granular exit tracking

### Database
- New `execution_json` column on `trades` table for live trade execution history
- New `exit_type` column on `fills` table (tp_hit, stop_hit, manual_exit, or NULL for imports)
- Auto-migration for both new columns on existing databases

### Settings
- Updated settings page layout and tag configuration improvements

---

## [1.0.0] — 2025-02-27

### Initial Release

Full-featured trade journaling application.

#### Core
- Flask web application with SQLite storage
- Three-layer architecture: `server.py` (HTTP) → `app_logic.py` (logic) → `database.py` (data)
- Auto-created database on first run
- Cross-platform launchers (`start_mac.sh`, `start_windows.bat`)

#### Journal
- CSV/Excel drag-and-drop import with FIFO position tracking
- Round-trip trade reconstruction from raw fills
- Day view with individual trade breakdown
- Trade detail page with fills table, tags, notes, and screenshots

#### Live Trade Entry — Ticket UI
- Single-page "Ticket" interface at `/live` — no scrolling, no page transitions
- Command bar: toggle direction (L/S), instrument (MES/ES), mode (Full/3-Way), enter price + qty
- One-click exit buttons (TP1/TP2/TP3) pre-filled with price, qty, and P&L estimate
- Partials mode: 3-way qty split with independent stops/targets per portion
- Inline price editing: click any stop/target value in position map to edit
- Trail stops: per-portion stop adjustment with instant risk recalculation
- Directional risk calculation: trailing stop past entry shows locked profit (green), not risk
- Net risk = sum of all stop outcomes + realized P&L (signed, color-coded)
- Manual exit distributes qty across open portions sequentially
- Notes auto-save, tags via slide-out panel
- "Save & Push to Journal" creates full journal entry with fills, tags, and notes
- Day P&L footer with cumulative realized P&L
- Legacy form-based UI preserved at `/live-legacy`

#### Portfolios
- Create, rename, color-code, and delete portfolios
- Global portfolio selector in nav filters all views
- Per-portfolio analytics

#### Analytics
- Daily P&L bar chart
- Time-of-day average P&L by entry hour
- Average P&L per "With" factor
- Win rate by setup type
- Full tag performance table filterable by group

#### Tag System
- 7 tag groups: With, Against, Volume, Exit, Setup, Pre-Trade, Entry
- Multi-select and single-select groups
- Fully customizable in Settings: add, remove, reorder (drag), rename
- Tags persist through live trade → journal push

#### Theme System
- 9 built-in themes: Mint Terminal, Amber Terminal, Cyan Focus, Arctic Blue, Crimson Edge, Purple Haze, Monochrome, Paper Light, Soft Dark
- Instant switching (no reload) via CSS custom properties
- Persisted in localStorage (instant paint) and database (sync)
- Theme picker with color swatch previews in Settings
- 22 CSS variables per theme covering background, surfaces, borders, text, accents, glows, and button states

#### Settings
- Theme picker (9 themes with previews)
- Tag group configuration (drag-and-drop reorder, add/remove/rename)
- Instrument configuration (MES/ES dollars-per-point, dollars-per-tick, ticks-per-point)
- Trade defaults (stop/TP distances for full and partial modes)
- DB Admin: export full database as SQL, import from SQL backup

#### Database
- Auto-migration system for schema changes
- Export/import as lossless SQL round-trip
- Backup before import (timestamped `.bak` files)
- app_config table for settings persistence
