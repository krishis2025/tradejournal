# Trade Journal — Database Schema

## Entity Relationship Overview

```
accounts ──┬──< trading_days ──┬──< trades ──┬──< fills
            │                   │              ├──< trade_tags
            │                   │              ├──< trade_images
            │                   │              └──< shadow_trades
            │                   └──< day_images
            │
            ├──< account_config
            │
            ├──< live_trades ──┬──< live_trade_levels
            │                  ├──< live_trade_executions
            │                  └──< live_trade_images
            │
            ├──< developing_context ──< trade_strength
            └──< trade_strength

setups ──< setup_images

observations ──< observation_images

trading_days ──< market_internals

tag_config (standalone)
app_config (standalone)
```

`──<` = one-to-many

---

## Tables

### 1. ACCOUNTS
Primary table for managing trading accounts.

| Column             | Type    | Constraints                          |
|--------------------|---------|--------------------------------------|
| id                 | INTEGER | PK AUTOINCREMENT                     |
| name               | TEXT    | NOT NULL UNIQUE                      |
| description        | TEXT    | NOT NULL DEFAULT ''                  |
| color              | TEXT    | NOT NULL DEFAULT '#4fffb0'           |
| created_at         | TEXT    | NOT NULL DEFAULT datetime('now')     |
| account_size       | REAL    |                                      |
| default_qty        | INTEGER |                                      |
| default_instrument | TEXT    |                                      |
| is_primary         | INTEGER | NOT NULL DEFAULT 0                   |
| risk_per_trade_pct | REAL    |                                      |

---

### 2. TRADING_DAYS
Records of trading days per account.

| Column        | Type    | Constraints                              |
|---------------|---------|------------------------------------------|
| id            | INTEGER | PK AUTOINCREMENT                         |
| date          | TEXT    | NOT NULL                                 |
| account_id    | INTEGER | FK → accounts(id) ON DELETE SET NULL     |
| imported_at   | TEXT    | NOT NULL DEFAULT datetime('now')         |
| day_type      | TEXT    | NOT NULL DEFAULT ''                      |
| day_value     | TEXT    | NOT NULL DEFAULT ''                      |
| notes_well    | TEXT    | NOT NULL DEFAULT ''                      |
| notes_improve | TEXT    | NOT NULL DEFAULT ''                      |
| notes_lessons | TEXT    | NOT NULL DEFAULT ''                      |
| notes_focus   | TEXT    | NOT NULL DEFAULT ''                      |
| day_volume    | TEXT    | NOT NULL DEFAULT ''                      |
| day_score     | TEXT    | NOT NULL DEFAULT '0'                     |

`day_score` stores a JSON object mapping grade category names to score values (e.g. `{"Market Read":"Good","Entry Quality":"Poor"}`).

**Unique:** (date, account_id)

---

### 3. TRADES
Individual trades recorded per day.

| Column           | Type    | Constraints                                |
|------------------|---------|--------------------------------------------|
| id               | INTEGER | PK AUTOINCREMENT                           |
| day_id           | INTEGER | NOT NULL, FK → trading_days(id) ON DELETE CASCADE |
| trade_num        | INTEGER | NOT NULL                                   |
| direction        | TEXT    | NOT NULL                                   |
| qty              | INTEGER | NOT NULL                                   |
| avg_entry        | REAL    | NOT NULL                                   |
| avg_exit         | REAL    | NOT NULL                                   |
| pnl              | REAL    | NOT NULL                                   |
| entry_time       | TEXT    | NOT NULL                                   |
| exit_time        | TEXT    | NOT NULL                                   |
| is_open          | INTEGER | NOT NULL DEFAULT 0                         |
| notes            | TEXT    | NOT NULL DEFAULT ''                        |
| execution_json   | TEXT    |                                            |
| notes_monitoring | TEXT    | NOT NULL DEFAULT ''                        |
| notes_exit       | TEXT    | NOT NULL DEFAULT ''                        |
| execution_score_json | TEXT | nullable                                  |
| context_id       | INTEGER | nullable, FK → developing_context(id)     |

---

### 4. FILLS
Individual fill/execution records for trades.

| Column    | Type    | Constraints                              |
|-----------|---------|------------------------------------------|
| id        | INTEGER | PK AUTOINCREMENT                         |
| trade_id  | INTEGER | NOT NULL, FK → trades(id) ON DELETE CASCADE |
| fill_time | TEXT    | NOT NULL                                 |
| side      | TEXT    | NOT NULL                                 |
| qty       | INTEGER | NOT NULL                                 |
| price     | REAL    | NOT NULL                                 |
| exit_type | TEXT    |                                          |

---

### 5. TRADE_TAGS
Tags associated with trades.

| Column   | Type    | Constraints                              |
|----------|---------|------------------------------------------|
| id       | INTEGER | PK AUTOINCREMENT                         |
| trade_id | INTEGER | NOT NULL, FK → trades(id) ON DELETE CASCADE |
| group_id | TEXT    | NOT NULL                                 |
| tag      | TEXT    | NOT NULL                                 |

**Unique:** (trade_id, group_id, tag)

---

### 6. TAG_CONFIG
Custom tag configuration per tag group.

| Column   | Type    | Constraints            |
|----------|---------|------------------------|
| id       | INTEGER | PK AUTOINCREMENT       |
| group_id | TEXT    | NOT NULL               |
| tag      | TEXT    | NOT NULL               |
| position | INTEGER | NOT NULL DEFAULT 0     |
| enabled  | INTEGER | NOT NULL DEFAULT 1     |

**Unique:** (group_id, tag)

---

### 7. TRADE_IMAGES
Images attached to trades.

| Column      | Type    | Constraints                              |
|-------------|---------|------------------------------------------|
| id          | INTEGER | PK AUTOINCREMENT                         |
| trade_id    | INTEGER | NOT NULL, FK → trades(id) ON DELETE CASCADE |
| filename    | TEXT    | NOT NULL                                 |
| caption     | TEXT    | NOT NULL DEFAULT ''                      |
| uploaded_at | TEXT    | NOT NULL DEFAULT datetime('now')         |

---

### 8. APP_CONFIG
Application-wide key-value configuration.

| Column | Type | Constraints            |
|--------|------|------------------------|
| key    | TEXT | PK                     |
| value  | TEXT | NOT NULL DEFAULT ''    |

---

### 9. LIVE_TRADES
Active live trades during trading sessions.

| Column           | Type    | Constraints                            |
|------------------|---------|----------------------------------------|
| id               | INTEGER | PK AUTOINCREMENT                       |
| account_id       | INTEGER | FK → accounts(id) ON DELETE SET NULL   |
| status           | TEXT    | NOT NULL DEFAULT 'open'                |
| direction        | TEXT    | NOT NULL                               |
| instrument       | TEXT    | NOT NULL DEFAULT 'MES'                 |
| entry_price      | REAL    | NOT NULL                               |
| entry_time       | TEXT    | NOT NULL                               |
| total_qty        | INTEGER | NOT NULL                               |
| mode             | TEXT    | NOT NULL DEFAULT 'full'                |
| notes            | TEXT    | NOT NULL DEFAULT ''                    |
| tags_json        | TEXT    | NOT NULL DEFAULT '{}'                  |
| created_at       | TEXT    | NOT NULL DEFAULT datetime('now')       |
| closed_at        | TEXT    |                                        |
| realized_pnl     | REAL    | NOT NULL DEFAULT 0                     |
| journal_trade_id | INTEGER |                                        |
| notes_monitoring | TEXT    | NOT NULL DEFAULT ''                    |
| notes_exit       | TEXT    | NOT NULL DEFAULT ''                    |
| guard_json       | TEXT    | NOT NULL DEFAULT ''                    |

`guard_json` stores the pre-trade execution guard data as JSON: `{"tech":["developing_value","volume_tempo",...],"repeatable":true,"entry_mode":"strength","mental_state":"patient","score":20}`. Mental states: `patient` (+5), `intuition` (+3), `eager` (-5). Max score: 20.

---

### 10. LIVE_TRADE_LEVELS
Stop/TP levels for live trades.

| Column        | Type    | Constraints                                    |
|---------------|---------|------------------------------------------------|
| id            | INTEGER | PK AUTOINCREMENT                               |
| live_trade_id | INTEGER | NOT NULL, FK → live_trades(id) ON DELETE CASCADE |
| level_type    | TEXT    | NOT NULL                                       |
| portion       | INTEGER | NOT NULL DEFAULT 1                             |
| qty           | INTEGER | NOT NULL                                       |
| price         | REAL    | NOT NULL                                       |
| risk_dollars  | REAL    | NOT NULL DEFAULT 0                             |
| reward_dollars| REAL    | NOT NULL DEFAULT 0                             |

---

### 11. LIVE_TRADE_EXECUTIONS
Execution log for live trades.

| Column        | Type    | Constraints                                    |
|---------------|---------|------------------------------------------------|
| id            | INTEGER | PK AUTOINCREMENT                               |
| live_trade_id | INTEGER | NOT NULL, FK → live_trades(id) ON DELETE CASCADE |
| exec_type     | TEXT    | NOT NULL                                       |
| portion       | INTEGER | NOT NULL DEFAULT 1                             |
| qty           | INTEGER | NOT NULL                                       |
| price         | REAL    | NOT NULL                                       |
| exec_time     | TEXT    | NOT NULL                                       |
| pnl           | REAL    | NOT NULL DEFAULT 0                             |
| created_at    | TEXT    | NOT NULL DEFAULT datetime('now')               |

---

### 12. LIVE_TRADE_IMAGES
Images attached to live trades. Copied to `trade_images` on push to journal.

| Column        | Type    | Constraints                                    |
|---------------|---------|------------------------------------------------|
| id            | INTEGER | PK AUTOINCREMENT                               |
| live_trade_id | INTEGER | NOT NULL, FK → live_trades(id) ON DELETE CASCADE |
| filename      | TEXT    | NOT NULL                                       |
| caption       | TEXT    | NOT NULL DEFAULT ''                            |
| uploaded_at   | TEXT    | NOT NULL DEFAULT datetime('now')               |

---

### 13. SHADOW_TRADES
Projected trades for non-primary accounts.

| Column               | Type    | Constraints                                |
|----------------------|---------|--------------------------------------------|
| id                   | INTEGER | PK AUTOINCREMENT                           |
| source_trade_id      | INTEGER | NOT NULL, FK → trades(id) ON DELETE CASCADE |
| account_id           | INTEGER | NOT NULL, FK → accounts(id) ON DELETE CASCADE |
| projected_qty        | INTEGER | NOT NULL                                   |
| projected_instrument | TEXT    | NOT NULL DEFAULT 'MES'                     |
| projected_pnl        | REAL    | NOT NULL                                   |

**Unique:** (source_trade_id, account_id)

---

### 14. ACCOUNT_CONFIG
Per-account configuration settings.

| Column     | Type    | Constraints                                |
|------------|---------|--------------------------------------------|
| id         | INTEGER | PK AUTOINCREMENT                           |
| account_id | INTEGER | NOT NULL, FK → accounts(id) ON DELETE CASCADE |
| key        | TEXT    | NOT NULL                                   |
| value      | TEXT    | NOT NULL DEFAULT ''                        |

**Unique:** (account_id, key)

---

### 15. DAY_IMAGES
Images attached to trading days.

| Column      | Type    | Constraints                                    |
|-------------|---------|------------------------------------------------|
| id          | INTEGER | PK AUTOINCREMENT                               |
| day_id      | INTEGER | NOT NULL, FK → trading_days(id) ON DELETE CASCADE |
| filename    | TEXT    | NOT NULL                                       |
| caption     | TEXT    | NOT NULL DEFAULT ''                            |
| uploaded_at | TEXT    | NOT NULL DEFAULT datetime('now')               |

---

### 16. SETUPS
Trading setups catalog.

| Column          | Type    | Constraints                      |
|-----------------|---------|----------------------------------|
| id              | INTEGER | PK AUTOINCREMENT                 |
| name            | TEXT    | NOT NULL UNIQUE                  |
| description     | TEXT    | NOT NULL DEFAULT ''              |
| characteristics | TEXT    | NOT NULL DEFAULT ''              |
| created_at      | TEXT    | NOT NULL DEFAULT datetime('now') |

---

### 17. SETUP_IMAGES
Images attached to setups.

| Column      | Type    | Constraints                                |
|-------------|---------|-------------------------------------------|
| id          | INTEGER | PK AUTOINCREMENT                           |
| setup_id    | INTEGER | NOT NULL, FK → setups(id) ON DELETE CASCADE |
| filename    | TEXT    | NOT NULL                                   |
| caption     | TEXT    | NOT NULL DEFAULT ''                        |
| uploaded_at | TEXT    | NOT NULL DEFAULT datetime('now')           |

---

### 18. OBSERVATIONS
Market observations and notes.

| Column     | Type    | Constraints                                  |
|------------|---------|----------------------------------------------|
| id         | INTEGER | PK AUTOINCREMENT                             |
| date       | TEXT    | NOT NULL DEFAULT date('now','localtime')      |
| time       | TEXT    | NOT NULL DEFAULT ''                          |
| text       | TEXT    | NOT NULL DEFAULT ''                          |
| category   | TEXT    | NOT NULL DEFAULT 'general'                   |
| created_at | TEXT    | NOT NULL DEFAULT datetime('now','localtime') |

---

### 19. OBSERVATION_IMAGES
Images attached to observations.

| Column         | Type    | Constraints                                        |
|----------------|---------|----------------------------------------------------|
| id             | INTEGER | PK AUTOINCREMENT                                   |
| observation_id | INTEGER | NOT NULL, FK → observations(id) ON DELETE CASCADE  |
| filename       | TEXT    | NOT NULL                                           |
| caption        | TEXT    | NOT NULL DEFAULT ''                                |
| uploaded_at    | TEXT    | NOT NULL DEFAULT datetime('now')                   |

---

### 20. MARKET_INTERNALS
Daily market internals logged per session (morning, midday, afternoon).

| Column       | Type    | Constraints                                    |
|--------------|---------|------------------------------------------------|
| id           | INTEGER | PK AUTOINCREMENT                               |
| day_id       | INTEGER | NOT NULL, FK → trading_days(id) ON DELETE CASCADE |
| session      | TEXT    | NOT NULL (morning, midday, afternoon)          |
| timestamp    | TEXT    | DEFAULT ''                                     |
| structure    | TEXT    | DEFAULT ''                                     |
| value_area   | TEXT    | DEFAULT ''                                     |
| vix          | TEXT    | DEFAULT ''                                     |
| trin         | TEXT    | DEFAULT ''                                     |
| vol_pct      | TEXT    | DEFAULT ''                                     |
| vold_nyse    | TEXT    | DEFAULT ''                                     |
| vold_nq      | TEXT    | DEFAULT ''                                     |
| add_nyse     | TEXT    | DEFAULT ''                                     |
| add_nq       | TEXT    | DEFAULT ''                                     |
| adh          | TEXT    | DEFAULT ''                                     |
| sectors_json | TEXT    | DEFAULT '[]'                                   |
| tape_notes   | TEXT    | DEFAULT ''                                     |

**Unique:** (day_id, session)

`structure` values: Balanced, Trending, Short Covering, Liquidation, Thin Structure.
`value_area` values: Lower, Overlapping Lower, Overlapping, Overlapping Higher, Higher.
`sectors_json` stores a JSON array of `{ticker, value}` objects for sector weighting.

---

### 21. DEVELOPING_CONTEXT
Pre-trade context declarations for the Declare Setup flow.

| Column       | Type    | Constraints                            |
|--------------|---------|----------------------------------------|
| id           | INTEGER | PK AUTOINCREMENT                       |
| account_id   | INTEGER | FK → accounts(id) ON DELETE SET NULL   |
| date         | TEXT    | NOT NULL                               |
| time         | TEXT    | NOT NULL                               |
| mkt_read     | TEXT    | NOT NULL DEFAULT ''                    |
| value_area   | TEXT    | NOT NULL DEFAULT ''                    |
| setup        | TEXT    | NOT NULL DEFAULT ''                    |
| location     | TEXT    | NOT NULL DEFAULT ''                    |
| nuance       | TEXT    | NOT NULL DEFAULT ''                    |
| mental_state | TEXT    | NOT NULL DEFAULT 'calm'                |
| created_at   | TEXT    | NOT NULL DEFAULT datetime('now','localtime') |
| day_type     | TEXT    | NOT NULL DEFAULT ''                    |
| volume_read  | TEXT    | NOT NULL DEFAULT ''                    |
| trend        | TEXT    | NOT NULL DEFAULT ''                    |
| observation  | TEXT    | NOT NULL DEFAULT ''                    |
| plan_text    | TEXT    | NOT NULL DEFAULT ''                    |
| plan_location| TEXT    | NOT NULL DEFAULT ''                    |
| plan_trigger | TEXT    | NOT NULL DEFAULT ''                    |
| nuances_json | TEXT    | NOT NULL DEFAULT '[]'                  |
| notes        | TEXT    | NOT NULL DEFAULT ''                    |

`value_area` values: Lower, Overlapping Lower, Overlapping, Overlapping Higher, Higher.
`mental_state` values: calm (passed mental state check).
`day_type`: Free text describing market day type (e.g. "Liquidation break", "Balancing").
`volume_read`: Free text describing volume conditions (e.g. "Low selling volume").
`trend`: Market trend — typically "Up", "Down", or "Neutral".
`observation`: Narrative context/reasoning (supplements `nuance`).
`plan_text`: Actionable trade plan (supplements `setup`).
`plan_location`: Where to execute the plan (supplements `location`).
`plan_trigger`: Condition that triggers entry.
`nuances_json`: JSON array of short nuance observations (e.g. `["Buyers failed at ONH","Volume drying up"]`).
`notes`: Longer narrative notes/context.

Old fields (`mkt_read`, `setup`, `location`, `nuance`) are backfilled from new fields for backward compatibility.

---

### 22. TRADE_STRENGTH
Pre-entry trade strength questionnaire capturing conviction data before trade entry.

| Column       | Type    | Constraints                                      |
|--------------|---------|--------------------------------------------------|
| id           | INTEGER | PK AUTOINCREMENT                                 |
| context_id   | INTEGER | FK → developing_context(id) ON DELETE SET NULL   |
| account_id   | INTEGER | FK → accounts(id) ON DELETE SET NULL             |
| value        | INTEGER | NOT NULL DEFAULT 0 (0=No, 1=Yes)                |
| volume       | INTEGER | NOT NULL DEFAULT 0 (0=No, 1=Yes)                |
| trend        | INTEGER | NOT NULL DEFAULT 0 (0=No, 1=Yes)                |
| adh          | INTEGER | NOT NULL DEFAULT 0 (0=No, 1=Yes)                |
| mental_state | TEXT    | NOT NULL DEFAULT 'calm' (calm, fomo)             |
| confidence   | TEXT    | NOT NULL DEFAULT 'medium' (low, medium, high)    |
| created_at   | TEXT    | NOT NULL DEFAULT datetime('now','localtime')     |

---

### LIVE_TRADES (updated)
Added columns:

| Column      | Type    | Constraints |
|-------------|---------|-------------|
| context_id  | INTEGER | nullable    |
| strength_id | INTEGER | nullable, FK → trade_strength(id) |

`context_id` links a live trade to the `developing_context` entry that was active when the trade was entered.
`strength_id` links a live trade to the `trade_strength` questionnaire completed before entry.

---

## Foreign Key Summary

### CASCADE deletes (deleting parent removes children):
| Parent         | Child                  | FK Column        |
|----------------|------------------------|------------------|
| trading_days   | trades                 | day_id           |
| trades         | fills                  | trade_id         |
| trades         | trade_tags             | trade_id         |
| trades         | trade_images           | trade_id         |
| trades         | shadow_trades          | source_trade_id  |
| accounts       | shadow_trades          | account_id       |
| accounts       | account_config         | account_id       |
| trading_days   | day_images             | day_id           |
| live_trades    | live_trade_levels      | live_trade_id    |
| live_trades    | live_trade_executions  | live_trade_id    |
| live_trades    | live_trade_images      | live_trade_id    |
| setups         | setup_images           | setup_id         |
| observations   | observation_images     | observation_id   |
| trading_days   | market_internals       | day_id           |

### SET NULL on delete (parent deletion nullifies FK):
| Parent              | Child               | FK Column    |
|---------------------|---------------------|--------------|
| accounts            | trading_days        | account_id   |
| accounts            | live_trades         | account_id   |
| accounts            | developing_context  | account_id   |
| accounts            | trade_strength      | account_id   |
| developing_context  | trade_strength      | context_id   |

---

## Indexes

| Index Name         | Table                  | Column(s)       |
|--------------------|------------------------|-----------------|
| idx_trades_day     | trades                 | day_id          |
| idx_fills_trade    | fills                  | trade_id        |
| idx_tags_trade     | trade_tags             | trade_id        |
| idx_tags_group     | trade_tags             | group_id        |
| idx_days_date      | trading_days           | date            |
| idx_days_account   | trading_days           | account_id      |
| idx_images_trade   | trade_images           | trade_id        |
| idx_live_levels    | live_trade_levels      | live_trade_id   |
| idx_live_execs     | live_trade_executions  | live_trade_id   |
| idx_live_images    | live_trade_images      | live_trade_id   |
| idx_shadow_source  | shadow_trades          | source_trade_id |
| idx_shadow_account | shadow_trades          | account_id      |
| idx_acct_config    | account_config         | account_id      |
| idx_day_images_day | day_images             | day_id          |
| idx_setup_images   | setup_images           | setup_id        |
| idx_obs_date       | observations           | date            |
| idx_obs_images     | observation_images     | observation_id  |
| idx_internals_day  | market_internals       | day_id          |
| idx_dev_ctx_date   | developing_context     | date            |

---

## Notes
- Database: **SQLite** with WAL mode enabled and foreign keys enforced
- All dates stored as ISO text (e.g. `2026-03-15`)
- All times stored as text (e.g. `10:30`)
- Boolean flags use INTEGER (0/1)
- JSON data stored as TEXT (e.g. `tags_json`, `execution_json`)
