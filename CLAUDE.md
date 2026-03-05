# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Start

```bash
# Create venv and install deps
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Run the app (port 5000)
.venv/bin/python3 server.py

# Or use the launcher scripts
bash start_mac.sh        # macOS/Linux
start_windows.bat        # Windows
```

Note: macOS port 5000 may conflict with AirPlay Receiver. Use `--port 5050` or kill the AirPlay process.

## Architecture

Three-layer separation — no layer reaches into another's domain:

```
server.py  (HTTP)  →  app_logic.py  (Logic)  →  database.py  (Data)
Flask routes only     CSV parsing, trade        SQLite schema,
                      reconstruction, risk      queries, migrations
                      math, tag definitions
```

- **No build step** — Flask + Jinja2 server-rendered templates with inline CSS/JS
- **SQLite** with WAL mode, auto-migration via `PRAGMA table_info()` checks in `init_db()`
- **Chart.js 4.4.1** loaded from CDN for all visualizations
- **CSS custom properties** for 9 themes — persisted in both `localStorage` (instant paint) and `app_config` table (sync)

## Key Patterns

- All templates extend `base.html` which provides `.page` layout (max-width 1200px), nav bar, theme engine, global CSS utilities
- Tag system: 6 groups defined in `app_logic.TAG_GROUPS`, customizable via `tag_config` table. Use `logic.get_tag_groups()` to get merged defaults+custom
- `settings.html` uses a sidebar pattern (`.settings-layout`, `.settings-sidebar`, `.sidebar-item`) reusable for other pages
- Trade P&L uses `$5/point` for MES and `$50/point` for ES (configurable in `app_logic.INSTRUMENT_CONFIG`)
- Data stored in `data/journal.db` (git-ignored) and `data/images/` (git-ignored)

## Database

- `database.py:init_db()` creates all tables and runs migrations on every request via `@app.before_request`
- Safe migrations use `PRAGMA table_info()` to check before `ALTER TABLE`
- Key tables: `trading_days`, `trades`, `fills`, `trade_tags`, `live_trades`, `live_trade_levels`, `live_trade_executions`, `portfolios`, `app_config`, `tag_config`

## Testing

No test framework — verify manually by running the Flask app. Use Flask test client for quick validation:

```python
.venv/bin/python3 -c "
from server import app
with app.test_client() as c:
    r = c.get('/analytics')
    print(r.status_code)
"
```

## Version Management

- `VERSION` file contains the current version string (e.g., `1.2.0`)
- `CHANGELOG.md` documents all notable changes per version
