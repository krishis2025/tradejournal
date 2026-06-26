# Changelog

All notable changes to Trade Journal are documented here.

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
