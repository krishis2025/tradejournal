# Deploying Trade Journal as a Multi-User App

## Context
The trade journal is currently a **single-user, local-only** Flask app. It uses SQLite, stores images on the local filesystem, has zero authentication, and runs on Flask's development server at `localhost:5050`. The question: what would it take to make this deployable and multi-user?

---

## Current State Summary

| Aspect | Current |
|--------|---------|
| Database | SQLite file (`data/journal.db`) |
| Auth | None — single implicit user |
| Server | Flask dev server, localhost only |
| Images | Local filesystem (`data/images/`) |
| Config | Hardcoded + SQLite `app_config` table |
| Dependencies | Flask + openpyxl only |
| Deployment files | None (no Dockerfile, Procfile, etc.) |

---

## What Needs to Change (4 Workstreams)

### 1. Authentication & User Isolation (biggest lift)

**Add a `users` table:**
```
users: id, email, password_hash, created_at
```

**Add `user_id` foreign key to:**
- `accounts` (already has multi-account — just needs user ownership)
- `trading_days`, `live_trades` (cascade through accounts)
- `app_config`, `tag_config` (per-user settings)

**Auth system options:**
- **Flask-Login + bcrypt** — simplest, session-based, fits the existing server-rendered architecture
- **JWT** — overkill unless building a separate API + SPA later

**Work involved:**
- `database.py`: Add users table to `init_db()`, add `user_id` column to accounts, migration for existing data
- `server.py`: Add login/register/logout routes, `@login_required` decorator on all routes, filter all queries by `current_user.id`
- New templates: `login.html`, `register.html`
- Every DB query that touches accounts/trades needs a user filter (there are ~50+ queries in `database.py`)

**Estimated scope:** ~500-800 lines across database.py, server.py, and new templates

---

### 2. Database: SQLite → PostgreSQL

**Why:** SQLite doesn't handle concurrent writes from multiple users well. WAL mode helps but isn't enough for a real deployment.

**Options:**
- **Option A: Stay on SQLite** — viable if you only expect <5 concurrent users and deploy on a single server. Simplest path.
- **Option B: Migrate to PostgreSQL** — proper multi-user support, connection pooling, cloud-managed options (Supabase, Neon, RDS)

**If going Postgres:**
- Replace `sqlite3` calls in `database.py` with `psycopg2` or use SQLAlchemy as an ORM
- Convert SQLite-specific syntax (`datetime('now')`, `PRAGMA`, `AUTOINCREMENT`) to Postgres equivalents
- Use `DATABASE_URL` environment variable for connection string
- Add connection pooling (psycopg2.pool or pgbouncer)

**Estimated scope:** If using raw psycopg2, ~300 lines of changes in database.py. If adopting SQLAlchemy, much larger rewrite.

**Recommendation:** Start with SQLite for a personal multi-user deploy (just you + a few friends). Move to Postgres only when you actually need it.

---

### 3. Image Storage: Filesystem → Cloud

**Current:** Images saved to `data/images/`, served via Flask route.

**Options:**
- **Option A: Keep filesystem** — works fine on a single VPS. Just make sure `data/images/` is on a persistent volume.
- **Option B: S3/Cloudflare R2** — better for scale, but adds complexity. Replace `save_to_disk()` with `upload_to_s3()`, serve via CDN URL instead of Flask route.

**Recommendation:** Keep filesystem storage for initial deployment. It works on any VPS. Move to S3/R2 later if needed.

---

### 4. Deployment Infrastructure

**Minimum viable deployment (VPS like DigitalOcean $6/mo, Railway, or Render):**

1. **Production server:** Add `gunicorn` to requirements, create `Procfile` or `gunicorn.conf.py`
2. **Reverse proxy:** nginx in front of gunicorn (handles SSL, static files, buffering)
3. **SSL:** Let's Encrypt via certbot, or use a platform that handles it (Railway, Render)
4. **Environment variables:** Move secrets (SECRET_KEY, DATABASE_URL) to env vars
5. **Dockerfile** (optional but recommended):
   ```dockerfile
   FROM python:3.11-slim
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install -r requirements.txt
   COPY . .
   CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "server:app"]
   ```

**New dependencies:**
```
gunicorn
flask-login
bcrypt
python-dotenv
```

---

## Recommended Phased Approach

### Phase 1: Make it deployable (no auth yet, just you)
- Add gunicorn, Dockerfile, `.env` support
- Change `127.0.0.1` → `0.0.0.0`, read config from env vars
- Add `SECRET_KEY` for Flask sessions
- Deploy to a VPS or Railway
- **Effort: ~2-3 hours**

### Phase 2: Add authentication
- Users table, Flask-Login, login/register pages
- Add `user_id` to accounts, filter all queries
- Protect all routes with `@login_required`
- **Effort: ~1-2 days**

### Phase 3: Polish for multi-user (optional)
- Migrate to PostgreSQL if needed
- Move images to S3/R2 if needed
- Add rate limiting, logging, error monitoring
- **Effort: ~1-2 days**

---

## Key Files to Modify
- `server.py` — auth routes, `@login_required`, env var config
- `database.py` — users table, `user_id` columns, query filters
- `requirements.txt` — new dependencies
- New: `Dockerfile`, `.env.example`, `templates/login.html`, `templates/register.html`

## Verification
1. Deploy Phase 1 → app accessible at a public URL, works as single-user
2. Deploy Phase 2 → register two accounts, verify data isolation (user A can't see user B's trades)
3. Test image uploads, live trades, CSV import all work per-user
