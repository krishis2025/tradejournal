# Trade Journal — Project Specification

> **Status:** Living document. Current app version: **v4.0.4** (see git tags / `CHANGELOG.md`).
> Companion docs: [`README.md`](README.md) (setup & usage), [`SCHEMA.md`](SCHEMA.md) (full DB schema),
> [`CHANGELOG.md`](CHANGELOG.md) (release history), [`deploy.md`](deploy.md) (future multi-user plan).
>
> _Note: the `VERSION` file (1.3.0) and `README.md` are out of date relative to the v4.x feature set
> described here. Treat git history + this spec as the source of truth._

---

## 1. Purpose & Scope

Trade Journal is a **local-first, single-user web app** for discretionary **ES / MES futures** traders.
It exists to turn raw broker fills and in-the-moment trading decisions into a structured, reviewable
record — so the trader can study execution quality, market context, and behavioral patterns over time.

The app is **post-execution journaling first** (it has no live market data feed), with a set of
"live"/"ticket" tools that help plan and record a trade as it is worked rather than streaming prices.

### In scope
- Importing broker fills (CSV/Excel) and reconstructing round-trip trades via FIFO.
- Recording trades, fills, tags, notes, and screenshots per trading day.
- Planning/working a trade through ticket-style UIs with risk/reward math.
- Capturing market context, setups, observations, and market internals.
- Multi-account ("portfolio") organization with shadow-trade projection across account sizes.
- Position-sizing guidance and analytics across many dimensions.
- Self-grading of execution and day quality.

### Out of scope (explicitly)
- **No live price feed / no broker connectivity.** The app journals trades *after* (or as) they happen;
  prices are entered by the user. _(See memory: `feedback_journaling_not_live`.)_
- No accounts/auth, no cloud, no telemetry. All data is a local SQLite file.
- Not an order-routing or execution system.

### Primary user
A solo discretionary futures trader (the app owner) running it on their own machine
(macOS primary, Windows supported). See `deploy.md` for the eventual multi-user direction.

---

## 2. Design Principles

1. **Local-first & private.** Everything lives in `data/journal.db`. No network calls required after
   first dependency install. The git repo is the sync mechanism between machines (DB is git-ignored).
2. **Strict three-layer separation.** HTTP, business logic, and data never reach into each other's
   domain (see §4).
3. **Speed during active trading.** Ticket UIs favor keyboard-driven, one-click interactions.
4. **Customizable taxonomy.** Tags, setups, instruments, and grading categories are user-editable, not
   hardcoded into workflows.
5. **Non-destructive evolution.** DB auto-migrates additively on startup; older code ignores new
   columns so branch-switching never corrupts data.
6. **Theme-adaptive UI.** All UI is built against CSS custom properties so 9 themes work without
   per-component overrides.

---

## 3. Technology Stack

| Concern        | Choice |
|----------------|--------|
| Language       | Python 3.9+ |
| Web framework  | Flask 3.0+ |
| File parsing   | openpyxl (Excel), stdlib `csv` |
| Database       | SQLite (WAL mode), accessed via `database.py` |
| Frontend       | Server-rendered Jinja2 templates + vanilla JS (no SPA framework) |
| Charts         | Client-side JS in `analytics.html` |
| Fonts          | Inter (default UI), JetBrains Mono / IBM Plex Sans in specific surfaces |
| Runtime        | Single local Flask server at `http://localhost:5000` |

Dependencies (`requirements.txt`): `flask>=3.0.0`, `openpyxl>=3.1.0`. Everything else is stdlib.

Launchers: `start_mac.sh` (macOS/Linux), `start_windows.bat` (Windows), `TradeJournal.command`.

---

## 4. Architecture

Three layers, no cross-domain reach-through:

| Layer     | File          | Responsibility |
|-----------|---------------|----------------|
| **HTTP**  | `server.py`   | Flask routes, request parsing, response shaping, page rendering. |
| **Logic** | `app_logic.py`| CSV/Excel parsing, FIFO trade reconstruction, risk/PnL math, live-trade plans, shadow trades, scoring. |
| **Data**  | `database.py` | SQLite schema definition, migrations, all queries. |

Supporting:
- `templates/` — Jinja2 pages (one per major view; see §6).
- `static/css`, `static/js` — shared styles and scripts.
- `data/journal.db` — the database (git-ignored). `data/images/` — uploaded screenshots (git-ignored).

### Key logic responsibilities (`app_logic.py`)
- **Import pipeline:** `parse_uploaded_file` → `reconstruct_trades` (`_build_round_trips`, FIFO) →
  `_compute_stats` → `save_day_trades` / `import_file`.
- **Instrument economics:** `INSTRUMENT_CONFIG` — `MES` = $5/pt ($1.25/tick), `ES` = $50/pt
  ($12.50/tick), 4 ticks/point. Used by all PnL and risk math.
- **Live trade engine:** `compute_live_trade_plan`, `compute_execution_pnl`, `recalculate_live_trade`,
  `close_live_trade_to_journal`.
- **Shadow trades:** `generate_shadow_trades`, `regenerate_all_shadows` — project a primary account's
  trades onto other accounts' sizes/instruments.
- **Scoring:** entry/review/trade execution scores, `compute_day_score`, `compute_combined_day_score`,
  grade categories with hints.
- **Taxonomies:** tag groups, observation categories/groups, day-type/value/volume tags.

---

## 5. Data Model (overview)

Full column-level detail lives in [`SCHEMA.md`](SCHEMA.md). High-level entity map:

```
accounts ──┬──< trading_days ──┬──< trades ──┬──< fills
           │                   │             ├──< trade_tags
           │                   │             ├──< trade_images
           │                   │             └──< shadow_trades
           │                   ├──< day_images
           │                   └──< market_internals
           ├──< account_config
           ├──< live_trades ──┬──< live_trade_levels
           │                  ├──< live_trade_executions
           │                  └──< live_trade_images
           └──< developing_context ──< trade_strength

setups ──< setup_images
observations ──< observation_images
signal_library / market_signals / trade_plan_legs / headline_helper
tag_config / app_config            (standalone)
```

**Core concepts:**
- **Account** — a trading account/strategy ("portfolio"), with size, default qty/instrument, risk %,
  color, and a single `is_primary` flag used for shadow projection.
- **Trading day** — trades grouped by date, per account; carries notes, images, and a day grade.
- **Trade** — a reconstructed round trip with fills, tags (7 groups), notes, images, execution score.
- **Live trade** — a planned/worked trade with levels (stops/targets), executions, and review score;
  can be pushed to the journal as a real trade.
- **Shadow trade** — a derived projection of a primary trade onto another account's size/instrument.
- **Developing context / trade strength** — pre-trade market read, signals, plan legs, and a strength
  score (powers the Context Ribbon / Trade Plan).
- **Setups / Observations** — reusable setup library and a dated observation log, both with images.
- **Market internals** — per-session (per trading day) internals snapshot.

**Migrations:** `database.py` creates tables `IF NOT EXISTS` and performs additive migrations on
startup. New columns are safe across branch switches (older code ignores them).
_(See memory: always update `SCHEMA.md` when the schema changes.)_

---

## 6. Application Surface (navigation & routes)

Top nav (from `templates/base.html`): **Journal · Live Trade · Trade V2 · Accounts · Simulation ·
Analytics · Setups · Observations · Settings**, plus a global account selector.

### Pages
| Route | Template | Purpose |
|-------|----------|---------|
| `/` | `index.html` | Journal dashboard: all trading days; CSV/Excel import drop zone. |
| `/day/<id>` · `/day/<date>` | `day.html` | Day view: expandable trade trays, fills, tags, day notes/images. |
| `/trade/<id>` | `trade.html` | Trade Execution view: single trade detail + tagging. |
| `/trade/<id>/v2` | `trade_v2.html` | V2 trade detail. |
| `/live` | `live_ticket.html` | Live Trade "Ticket" UI (current primary live entry). |
| `/live-v2` | `live_v2.html` | Trade V2 live view (Context Ribbon / Headline Bar). |
| `/live-legacy`, `/live-legacy/new`, `/live-legacy/<id>` | `live_*_legacy.html` | Legacy form/list live UI. |
| `/accounts` | `accounts.html` | Account management + sizing cheat sheet. |
| `/simulation` | `simulation.html` | Simulation view. |
| `/analytics` | `analytics.html` | P&L chart, time-of-day, win-rate-by-setup, tag performance. |
| `/setups`, `/setup/<id>` | `setups.html`, `setup_detail.html` | Setup library + detail. |
| `/observations` | `observations.html` | Observation log. |
| `/day/<id>/internals`, `/day/<id>/internals-v2` | `internals.html`, `internals_v2.html` | Market internals per day. |
| `/settings` | `settings.html` | Tags, themes, instruments, trade defaults, DB admin. |
| `*` | `404.html` | Not found. |

### API surface (`/api/...`, summarized)
- **Import & days:** `/api/import`, `/api/day/create`, `/api/day/<id>` (DELETE), day notes/images.
- **Trades:** tags, notes, images, image captions.
- **Accounts:** CRUD, list, `/api/shadow/regenerate`.
- **Live trades:** full lifecycle — create, get/update/delete, levels, execute, add, exit, stop(s),
  stop-hit, push (to journal), cancel, review-score, recalc, images, session summary.
- **Context / strength:** `/api/context*`, `/api/leg/<id>`, `/api/trade-strength*`, `/api/signals*`,
  `/api/headline-helpers*`.
- **Setups / observations:** CRUD + images.
- **Market internals:** per-day and "today" GET/POST per session.
- **Settings:** theme get/set, tags per group + reset, trade defaults, instruments.
- **DB admin:** `/api/db/export` (SQL dump), `/api/db/import` (restore).
- **Analytics:** `/api/analytics`.

_(Route line numbers are not part of the contract — see `server.py` for the authoritative list.)_

---

## 7. Key Workflows

### 7.1 Import → reconstruct
1. User drops a broker CSV/Excel on the dashboard import zone (`/api/import`).
2. `parse_uploaded_file` reads rows; `_parse_fill_time` / `_parse_date` normalize timestamps.
3. `reconstruct_trades` → `_build_round_trips` groups fills into round trips via FIFO position tracking.
4. `_compute_stats` derives direction, avg entry/exit, qty, and P&L (instrument-aware).
5. `save_day_trades` persists day → trades → fills.

**Required CSV columns:** `B/S`, `avgPrice`, `filledQty`, `Fill Time` (`MM/DD/YYYY HH:MM:SS`), `Date`.
Sample file: `Orders19.csv`.

### 7.2 Live trade lifecycle
Create plan (`compute_live_trade_plan`, optional Partials/3-way split) → set levels → execute / add /
exit fills → adjust stops (trailing, locked-profit detection) → `recalculate_live_trade` keeps
risk/reward live → **push to journal** (`close_live_trade_to_journal`) creates a real trade with fills,
tags, notes. Includes the **Execution Guard** (PREP-mode mental-state checkpoint on ENTER).

### 7.3 Shadow projection
With one account marked primary, `generate_shadow_trades` projects each primary trade onto other
accounts using their size/instrument so cross-account performance can be compared without re-entry.

### 7.4 Review & grading
Trades get execution scores; days get a combined grade (`compute_combined_day_score`) blending a
day-level grade with per-trade execution quality, using user-editable grade categories + hints.

---

## 8. Customization & Taxonomy

- **Tag groups (7):** With, Against, Volume, Exit, Setup, Pre-Trade, Entry — each multi/single-select,
  fully editable in Settings (add/remove/reorder/rename), stored in `tag_config`.
- **Instruments:** MES/ES economics configurable; defaults per account.
- **Themes (9):** Mint, Amber, Cyan, Arctic Blue, Crimson, Purple, Monochrome, Paper Light, Soft Dark —
  applied instantly via CSS custom properties, persisted in `app_config`.
- **Setups, observation categories, grade categories:** user-defined.

---

## 9. Data, Backup & Sync

- Single SQLite DB at `data/journal.db` (WAL: `-shm`/`-wal` sidecars). Git-ignored.
- **Backup/restore:** Settings → DB Admin → Export (`.sql` dump) / Import — lossless round trip.
  Or copy `data/journal.db` directly. Timestamped `.bak_*` files exist under `data/`.
- **Cross-machine sync:** push/pull the repo for code; move the DB via export/import or direct copy.

---

## 10. Conventions for Contributors

- **Respect the three layers.** Routes in `server.py`, math/parsing in `app_logic.py`, SQL in
  `database.py`. Don't put SQL in routes or HTTP handling in logic.
- **Update `SCHEMA.md`** whenever the DB schema changes _(project rule)_.
- **Internals parity:** changes to `internals_v2.html` must be mirrored in `live_v2.html`
  _(project rule)_.
- **Fonts:** default to `Inter, sans-serif` app-wide; Market Internals uses Inter + JetBrains Mono
  _(project rules)_.
- **No live price feed.** Don't design features assuming streaming market data.
- **Keep migrations additive** so branch-switching stays safe; bump `CHANGELOG.md` and version on
  releases.
- **Flag deployment-hostile decisions** — multi-user deployment is a planned direction (`deploy.md`).

---

## 11. Roadmap / Future Direction

- **Multi-user deployment** (auth, hosted DB, per-user isolation) — see `deploy.md`. Currently
  single-user, local-only by design.
- Dynamic trade model (introduced in v4.0.0) continues to evolve (Context Ribbon, Trade Plan legs,
  signals, strength scoring).

---

_Last updated to reflect repository state at v4.0.4. When this drifts from the code, the code +
`SCHEMA.md` + `CHANGELOG.md` win — update this file to match._
