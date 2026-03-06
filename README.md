# Trade Journal

A local-first trade journaling app for ES/MES futures discretionary traders. Import fills from CSV/Excel, manage live trades with real-time risk tracking, tag trades by market context, and analyze performance across dimensions.

![Python](https://img.shields.io/badge/python-3.9+-blue)
![Flask](https://img.shields.io/badge/flask-3.0+-green)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-orange)

---

## Features

- **CSV/Excel Import** — Drag-and-drop fills from your broker, auto-grouped into round-trip trades via FIFO position tracking
- **Live Trade Entry** — Single-page "Ticket" interface: one-click exits, inline price editing, real-time risk/reward, trailing stops
- **Partials Mode** — 3-way split with independent stops/targets per portion, locked-profit detection on trailing stops
- **Tag System** — 7 tag groups (With, Against, Volume, Exit, Setup, Pre-Trade, Entry) fully customizable in Settings
- **Portfolios** — Separate trading accounts/strategies with colored indicators
- **Analytics** — Daily P&L chart, time-of-day analysis, win rate by setup, tag performance table
- **9 Themes** — Mint, Amber, Cyan, Arctic Blue, Crimson, Purple, Monochrome, Paper Light, Soft Dark
- **DB Admin** — Export/import full database as SQL backup
- **100% Local** — All data stays in a SQLite file on your machine. No accounts, no cloud, no tracking.

---

## Quick Start

### Requirements

- Python 3.9+ ([python.org](https://python.org))
- That's it. Everything else installs automatically.

### macOS / Linux

```bash
cd tradejournal
bash start_mac.sh
```

### Windows

Double-click `start_windows.bat` — it handles everything (venv, dependencies, launch).

The app opens automatically at **http://localhost:5000**

> **First time?** Make sure Python 3.9+ is installed from [python.org](https://python.org) and you check **"Add Python to PATH"** during the installer.

#### Manual setup (if the .bat doesn't work)

```cmd
cd tradejournal
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

Then open **http://localhost:5000** in your browser.

---

## Pulling Latest Changes (Windows)

If you already have the repo cloned on your Windows machine, open **Command Prompt** or **PowerShell** and run:

```cmd
cd C:\path\to\tradejournal
git pull
```

That's it — `git pull` downloads all the latest code changes from the remote.

If you had the app running, stop it first (Ctrl+C), pull, then restart:

```cmd
:: Stop the app with Ctrl+C, then:
git pull
start_windows.bat
```

> **If git pull shows merge conflicts**, run:
> ```cmd
> git stash
> git pull
> git stash pop
> ```
> This saves your local changes, pulls the latest, then re-applies your changes.

> **Don't have Git on Windows?** Download from [git-scm.com](https://git-scm.com/download/win). During install, keep the defaults. After install, open a new Command Prompt and `git` should work.

---

## Syncing Between Machines

This repo is your sync mechanism. Your trade data lives in `data/journal.db` which is **git-ignored** (it contains your personal trade data).

To move data between machines:
1. **Settings → DB Admin → Export** downloads a `.sql` backup file
2. Copy that file to your other machine
3. **Settings → DB Admin → Import** restores it

Or manually copy `data/journal.db` between machines.

---

## Project Structure

```
tradejournal/
├── server.py              ← HTTP layer (Flask routes only)
├── app_logic.py           ← Business logic (CSV parsing, trade reconstruction, risk calc)
├── database.py            ← Data layer (SQLite operations)
├── requirements.txt       ← Python dependencies
├── start_mac.sh           ← macOS/Linux launcher
├── start_windows.bat      ← Windows launcher
├── .gitignore
├── templates/
│   ├── base.html          ← Shared layout, nav, theme engine, global styles
│   ├── index.html         ← Dashboard: all trading days
│   ├── day.html           ← Day view: trades for one date
│   ├── trade.html         ← Single trade detail + tagging
│   ├── live_ticket.html   ← Live Trade: Ticket UI (current)
│   ├── live_entry_legacy.html  ← Live Trade: Legacy form-based UI
│   ├── live_list_legacy.html   ← Live Trade: Legacy list view
│   ├── analytics.html     ← Charts and tag performance
│   ├── portfolios.html    ← Portfolio management
│   ├── settings.html      ← Tags, themes, instruments, DB admin
│   └── 404.html
├── static/
│   ├── css/
│   └── js/
└── data/
    ├── journal.db         ← SQLite database (auto-created, git-ignored)
    └── images/            ← Trade screenshots (git-ignored)
```

### Architecture

Three-layer separation — no layer reaches into another's domain:

| Layer | File | Responsibility |
|-------|------|---------------|
| **HTTP** | `server.py` | Flask routes, request/response handling |
| **Logic** | `app_logic.py` | CSV parsing, trade reconstruction, risk math, live trade calculations |
| **Data** | `database.py` | SQLite schema, queries, migrations |

---

## Importing Trades

1. Export fills from your broker as CSV or Excel
2. Dashboard → drag file onto the import zone (or click it)
3. Trades are reconstructed using FIFO position tracking

### Required CSV columns

| Column | Description |
|--------|-------------|
| `B/S` | `Buy` or `Sell` |
| `avgPrice` | Fill price |
| `filledQty` | Number of contracts |
| `Fill Time` | Datetime (`MM/DD/YYYY HH:MM:SS`) |
| `Date` | Trade date |

The included `Orders19.csv` is a sample you can import immediately.

---

## Live Trade Entry

The Ticket UI (`/live`) is a single-page interface designed for speed during active trading:

- **Command Bar** — Toggle direction/instrument/mode, enter price + qty, press Enter
- **One-Click Exits** — TP1/TP2/TP3 buttons pre-filled with price, qty, and P&L estimate
- **Inline Price Editing** — Click any stop/target price in the position map to edit
- **Trail Stops** — Per-portion stop adjustment with instant risk recalculation
- **Push to Journal** — Explicitly saves trade with fills, tags, and notes to the main journal

The legacy form-based UI is still available at `/live-legacy`.

---

## Theme System

9 built-in themes configurable in **Settings → Theme**:

| Theme | Style | Best for |
|-------|-------|----------|
| 🟢 Mint Terminal | Dark + mint green | Default, high contrast |
| 🟡 Amber Terminal | Dark + warm gold | Bloomberg feel |
| 🔵 Cyan Focus | Dark + electric blue | Modern, clean |
| ❄️ Arctic Blue | Dark + steel blue | Easy on eyes, long sessions |
| 🔴 Crimson Edge | Dark + red-orange | High energy |
| 🟣 Purple Haze | Dark + soft purple | Distinctive |
| ⚪ Monochrome | Dark + silver/white | Zero distraction |
| 📄 Paper Light | Light + dark green | Bright rooms |
| 🌙 Soft Dark | Medium dark + lavender | Reduced contrast |

Themes apply instantly (no reload) and persist across sessions.

---

## Tag System

| Group | Example Tags | Selection |
|-------|-------------|-----------|
| **With** | Value, Market Internals, ADH, AVWAP, VWAP | Multi |
| **Against** | Value, Market Internals, ADH, AVWAP, VWAP | Multi |
| **Volume** | Avg, Above Avg, Below Avg | Single |
| **Exit** | Planned, Fear / Anxious, Bailed Out | Single |
| **Setup** | With Value, Recapture of VWAP, Balance Fade | Single |
| **Pre-Trade** | Trade came to me, Boredom, Revenge Mindset | Multi |
| **Entry** | Waited, FOMO, Late, At AVWAP | Multi |

All tags are fully customizable in Settings (add, remove, reorder, rename).

---

## Data and Backup

All data is stored locally in `data/journal.db` (SQLite).

**Backup options:**
- Settings → DB Admin → Export (downloads `.sql` file)
- Copy `data/journal.db` directly
- Both methods are lossless round-trips

No internet connection required after first run.
