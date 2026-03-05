# Changelog

All notable changes to Trade Journal are documented here.

## [1.3.0] — 2026-03-04

### Analytics — Sidebar Redesign

#### Layout
- **Sidebar navigation**: Left sidebar (180px) with 5 sections — KPIs, Equity, Calendar, Time, Tags
- Each section renders independently (no long vertical scroll)
- **Lazy chart initialization**: Charts only render when their section is first visited (reduces initial load from 9 Chart.js instances to 1)
- Section state persisted in URL hash (`#kpis`, `#equity`, etc.) — survives page reloads

#### Date Range Filtering
- Global filter bar: All Time, This Week, This Month, Last 30 Days, Last 90 Days presets + custom date picker
- All charts, KPIs, and tables respect the selected date range

#### New KPIs
- Average Win / Average Loss with win-loss ratio
- Expectancy: (win_rate x avg_win) - (loss_rate x avg_loss)
- Profit Factor: gross profit / gross loss
- Average Trade Duration (entry to exit, in minutes)
- Trading Days count

#### New Charts
- **Equity Curve**: cumulative P&L line chart with fill and per-trade tooltips
- **Drawdown Chart**: red filled area showing drawdown from equity peak, max drawdown in subtitle
- **Calendar Heatmap**: monthly grid with day cells showing day number, P&L (color-coded), and trade count; click to navigate to day view
- **Trade Duration vs P&L**: scatter plot with wins (green), losses (red), breakeven (grey)

#### Tag Correlation Analysis (New)
- Replaces "Avg P&L — With Tags" chart
- Finds co-occurring tag combinations across different groups
- Ranked insight cards showing lift vs overall win rate, avg P&L, trade count, win rate bar
- Minimum 3 trades per combination, top 15 results by absolute lift

#### Pre-Trade Mindset
- Moved from Tag Analytics section to KPIs section (more prominent)

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
