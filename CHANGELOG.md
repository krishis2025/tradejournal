# Changelog

All notable changes to Trade Journal are documented here.

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
