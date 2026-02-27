"""
APPLICATION LAYER
Business logic: CSV/Excel parsing, trade reconstruction, tag definitions.
No HTTP, no SQL — only pure domain logic.
"""

import csv
import io
from datetime import datetime

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

import database as db


# ── Tag Definitions ───────────────────────────────────────────────────────────

TAG_GROUPS = [
    {
        "id": "with",
        "label": "With",
        "dot": "dot-with",
        "active_class": "active-with",
        "tags": ["Value", "Market Internals", "ADH", "AVWAP", "VWAP"],
        "multi": True,
    },
    {
        "id": "against",
        "label": "Against",
        "dot": "dot-against",
        "active_class": "active-against",
        "tags": ["Value", "Market Internals", "ADH", "AVWAP", "VWAP"],
        "multi": True,
    },
    {
        "id": "volume",
        "label": "Volume",
        "dot": "dot-vol",
        "active_class": "active-vol",
        "tags": ["Avg", "Above Avg", "Below Avg"],
        "multi": False,
    },
    {
        "id": "exit",
        "label": "Exit",
        "dot": "dot-exit",
        "active_class": "active-exit",
        "tags": ["Planned — Monitored Continuation", "Fear / Anxious"],
        "multi": False,
    },
    {
        "id": "setup",
        "label": "Setup",
        "dot": "dot-setup",
        "active_class": "active-setup",
        "tags": [
            "With Value", "Recapture of VWAP", "Break out of Range", "Initiative",
            "Low Tempo fade", "Balance Fade", "Look out of balance failed",
            "Gap fill failed", "No Setup", "Intuitive / Gut Feel"
        ],
        "multi": False,
    },
    {
        "id": "pre",
        "label": "Pre-Trade",
        "dot": "dot-pre",
        "active_class": "active-pre",
        "tags": [
            "Trade came to me", "Intuition / Mkt Feel", "Not sure about context",
            "Quick Profit Attitude", "Revenge Mindset", "Boredom", "Distracted"
        ],
        "multi": True,
    },
]


def get_tag_groups():
    """
    Return TAG_GROUPS with tags replaced by any custom DB config.
    Falls back to hardcoded defaults for groups not yet configured.
    """
    custom = db.get_tag_config()  # {group_id: [tag, ...]} or None
    if not custom:
        return TAG_GROUPS
    result = []
    for g in TAG_GROUPS:
        merged = dict(g)
        if g["id"] in custom:
            merged["tags"] = custom[g["id"]]
        result.append(merged)
    return result




REQUIRED_COLUMNS = {"B/S", "avgPrice", "filledQty", "Fill Time", "Date"}


def parse_uploaded_file(filename: str, file_bytes: bytes) -> list:
    ext = filename.rsplit(".", 1)[-1].lower()

    if ext == "csv":
        text = file_bytes.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    elif ext in ("xlsx", "xls"):
        if not HAS_OPENPYXL:
            raise ValueError("openpyxl is required for Excel. Run: pip install openpyxl")
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ws = wb.active
        headers = [str(c.value).strip() if c.value else "" for c in next(ws.iter_rows(max_row=1))]
        rows = [dict(zip(headers, row)) for row in ws.iter_rows(min_row=2, values_only=True)]
    else:
        raise ValueError(f"Unsupported file type: .{ext}. Upload CSV or XLSX.")

    if not rows:
        raise ValueError("File is empty.")

    missing = REQUIRED_COLUMNS - set(rows[0].keys())
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    fills = []
    for r in rows:
        if not r.get("Fill Time") or not r.get("B/S"):
            continue
        try:
            fills.append({
                "side":  str(r["B/S"]).strip(),
                "qty":   int(float(str(r["filledQty"]))),
                "price": float(r["avgPrice"]),
                "time":  _parse_fill_time(str(r["Fill Time"])),
                "date":  _parse_date(str(r["Date"])),
            })
        except (ValueError, KeyError, TypeError):
            continue

    if not fills:
        raise ValueError("No valid fills found in file.")

    return fills


def _parse_fill_time(raw: str) -> str:
    raw = raw.strip()
    for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%y %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).strftime("%H:%M:%S")
        except ValueError:
            pass
    parts = raw.split()
    return parts[1] if len(parts) >= 2 else raw


def _parse_date(raw: str) -> str:
    raw = raw.strip().split()[0]
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return raw


# ── Trade Reconstruction ──────────────────────────────────────────────────────

def reconstruct_trades(fills: list) -> list:
    """Group fills by date → reconstruct round-trip trades per date."""
    by_date: dict = {}
    for f in fills:
        by_date.setdefault(f["date"], []).append(f)

    return [
        {"date": date, "trades": _build_round_trips(sorted(day_fills, key=lambda x: x["time"]))}
        for date, day_fills in sorted(by_date.items())
    ]


def _build_round_trips(fills: list) -> list:
    position = 0
    current  = []
    trades   = []

    for f in fills:
        position += f["qty"] if f["side"] == "Buy" else -f["qty"]
        current.append(f)
        if position == 0:
            trades.append(_compute_stats(current, len(trades) + 1))
            current = []

    if current:  # unclosed position
        trades.append(_compute_stats(current, len(trades) + 1))

    return trades


def _compute_stats(fills: list, trade_num: int) -> dict:
    buy_qty = buy_val = sell_qty = sell_val = 0
    for f in fills:
        if f["side"] == "Buy":
            buy_qty += f["qty"];  buy_val  += f["qty"] * f["price"]
        else:
            sell_qty += f["qty"]; sell_val += f["qty"] * f["price"]

    is_short  = fills[0]["side"] == "Sell"
    qty       = max(buy_qty, sell_qty)

    # Gracefully handle partial/unclosed positions (e.g. today's open trade)
    avg_entry = (sell_val / sell_qty) if (is_short and sell_qty) else (buy_val / buy_qty if buy_qty else 0)
    avg_exit  = (buy_val  / buy_qty)  if (is_short and buy_qty)  else (sell_val / sell_qty if sell_qty else 0)

    # P&L is 0 for unclosed positions (no exit side yet)
    if (is_short and buy_qty == 0) or (not is_short and sell_qty == 0):
        pnl = 0.0
    else:
        pnl = ((avg_entry - avg_exit) if is_short else (avg_exit - avg_entry)) * qty * 5

    return {
        "trade_num":  trade_num,
        "direction":  "Short" if is_short else "Long",
        "qty":        qty,
        "avg_entry":  round(avg_entry, 4),
        "avg_exit":   round(avg_exit,  4),
        "pnl":        round(pnl, 2),
        "entry_time": fills[0]["time"],
        "exit_time":  fills[-1]["time"],
        "fills":      fills,
        "open":       (is_short and buy_qty == 0) or (not is_short and sell_qty == 0),
    }


# ── Persistence ───────────────────────────────────────────────────────────────

def save_day_trades(date: str, trades: list, portfolio_id=None) -> int:
    """
    Persist a full day of trades. Deletes and re-imports if day already exists
    for the same portfolio.
    """
    existing = db.get_day_by_date_portfolio(date, portfolio_id)
    if existing:
        db.delete_day(existing["id"])

    day_id = db.upsert_day(date, portfolio_id)

    for t in trades:
        trade_id = db.insert_trade(
            day_id, t["trade_num"], t["direction"], t["qty"],
            t["avg_entry"], t["avg_exit"], t["pnl"],
            t["entry_time"], t["exit_time"],
            is_open=t.get("open", False)
        )
        for f in t["fills"]:
            db.insert_fill(trade_id, f["time"], f["side"], f["qty"], f["price"])

    return day_id


def import_file(filename: str, file_bytes: bytes, portfolio_id=None) -> dict:
    """Full pipeline: parse → reconstruct → save. Returns summary dict."""
    fills     = parse_uploaded_file(filename, file_bytes)
    day_trades = reconstruct_trades(fills)

    saved = []
    for d in day_trades:
        day_id = save_day_trades(d["date"], d["trades"], portfolio_id)
        saved.append({
            "date":        d["date"],
            "day_id":      day_id,
            "trade_count": len(d["trades"]),
        })

    return {"days": saved}


# ── Live Trade Defaults & Config ─────────────────────────────────────────────

# Instrument tick values: (dollars_per_point, dollars_per_tick, ticks_per_point)
INSTRUMENT_CONFIG = {
    "MES": {"dollars_per_point": 5,  "dollars_per_tick": 1.25, "ticks_per_point": 4},
    "ES":  {"dollars_per_point": 50, "dollars_per_tick": 12.50, "ticks_per_point": 4},
}

# Default stop/TP distances in points
DEFAULT_TRADE_DEFAULTS = {
    "full_stop_points":    "20",
    "full_tp_points":      "20",
    "partial_stop_points": "20",
    "partial_tp1_points":  "5",
    "partial_tp2_points":  "10",
    "partial_tp3_points":  "20",
}


def get_trade_defaults():
    """Get trade default settings, merging DB config over hardcoded defaults."""
    config = db.get_all_config()
    result = {}
    for key, default_val in DEFAULT_TRADE_DEFAULTS.items():
        result[key] = config.get(f"td_{key}", default_val)
    return result


def get_instrument_config():
    """Get instrument tick values, with DB overrides."""
    config = db.get_all_config()
    result = {}
    for inst, defaults in INSTRUMENT_CONFIG.items():
        result[inst] = {
            "dollars_per_point": float(config.get(f"inst_{inst}_dpp", defaults["dollars_per_point"])),
            "dollars_per_tick":  float(config.get(f"inst_{inst}_dpt", defaults["dollars_per_tick"])),
            "ticks_per_point":   int(config.get(f"inst_{inst}_tpp",  defaults["ticks_per_point"])),
        }
    return result


def compute_live_trade_plan(direction, instrument, entry_price, total_qty, mode):
    """
    Compute stop/TP levels with risk/reward for a new live trade.
    Returns list of level dicts ready for DB insertion.
    """
    inst = get_instrument_config().get(instrument, INSTRUMENT_CONFIG["MES"])
    dpp = inst["dollars_per_point"]
    defaults = get_trade_defaults()
    is_long = direction == "Long"
    levels = []

    if mode == "full":
        stop_dist = float(defaults["full_stop_points"])
        tp_dist   = float(defaults["full_tp_points"])

        stop_price = entry_price - stop_dist if is_long else entry_price + stop_dist
        tp_price   = entry_price + tp_dist   if is_long else entry_price - tp_dist

        risk   = abs(entry_price - stop_price) * total_qty * dpp
        reward = abs(tp_price - entry_price)   * total_qty * dpp

        levels.append({"level_type": "stop", "portion": 1, "qty": total_qty,
                        "price": round(stop_price, 2), "risk_dollars": round(risk, 2), "reward_dollars": 0})
        levels.append({"level_type": "tp",   "portion": 1, "qty": total_qty,
                        "price": round(tp_price, 2),   "risk_dollars": 0, "reward_dollars": round(reward, 2)})
    else:
        # Partials — divide into 3
        stop_dist = float(defaults["partial_stop_points"])
        tp1_dist  = float(defaults["partial_tp1_points"])
        tp2_dist  = float(defaults["partial_tp2_points"])
        tp3_dist  = float(defaults["partial_tp3_points"])

        # Divide qty as evenly as possible
        base_qty = total_qty // 3
        remainder = total_qty % 3
        qtys = [base_qty, base_qty, base_qty]
        # Distribute remainder to first portions
        for i in range(remainder):
            qtys[i] += 1

        tp_dists = [tp1_dist, tp2_dist, tp3_dist]

        for i in range(3):
            stop_price = entry_price - stop_dist if is_long else entry_price + stop_dist
            risk = abs(entry_price - stop_price) * qtys[i] * dpp

            levels.append({"level_type": "stop", "portion": i + 1, "qty": qtys[i],
                            "price": round(stop_price, 2), "risk_dollars": round(risk, 2), "reward_dollars": 0})

            tp_price = entry_price + tp_dists[i] if is_long else entry_price - tp_dists[i]
            reward = abs(tp_price - entry_price) * qtys[i] * dpp

            levels.append({"level_type": "tp", "portion": i + 1, "qty": qtys[i],
                            "price": round(tp_price, 2), "risk_dollars": 0, "reward_dollars": round(reward, 2)})

    return levels


def compute_execution_pnl(direction, instrument, entry_price, exec_price, qty):
    """Calculate P&L for a single execution."""
    inst = get_instrument_config().get(instrument, INSTRUMENT_CONFIG["MES"])
    dpp = inst["dollars_per_point"]
    if direction == "Long":
        return round((exec_price - entry_price) * qty * dpp, 2)
    else:
        return round((entry_price - exec_price) * qty * dpp, 2)


def recalculate_live_trade(live_trade):
    """
    Given a full live_trade dict (with levels + executions),
    compute remaining qty, current risk, potential profit, realized P&L.
    
    Risk calculation:
    - For each remaining portion, compute distance from entry to stop
    - If stop is on the LOSING side of entry → that's risk (negative, red)
    - If stop is on the WINNING side of entry (trailing stop past entry) → that's locked profit (positive, green)
    - Net risk = sum of all portion risks - total realized P&L already banked
    """
    total_qty   = live_trade["total_qty"]
    executions  = live_trade.get("executions", [])
    levels      = live_trade.get("levels", [])
    entry_price = live_trade["entry_price"]
    direction   = live_trade["direction"]
    instrument  = live_trade["instrument"]
    mode        = live_trade["mode"]

    inst = get_instrument_config().get(instrument, INSTRUMENT_CONFIG["MES"])
    dpp = inst["dollars_per_point"]
    is_long = direction == "Long"

    # Realized P&L and qty from executions
    exited_qty = sum(e["qty"] for e in executions)
    realized_pnl = sum(e["pnl"] for e in executions)
    remaining_qty = total_qty - exited_qty

    # Initial risk (what it was at entry, for reference)
    initial_risk = 0
    for lv in levels:
        if lv["level_type"] == "stop":
            dist = abs(entry_price - lv["price"]) * lv["qty"] * dpp
            initial_risk += dist

    if remaining_qty <= 0:
        return {
            "remaining_qty":   0,
            "exited_qty":      exited_qty,
            "realized_pnl":    round(realized_pnl, 2),
            "current_risk":    0,
            "potential_reward": 0,
            "initial_risk":    round(initial_risk, 2),
            "active_portions": [],
            "portion_details": [],
            "is_closed":       True,
        }

    # Figure out which portions are still open and their real risk
    portion_details = []  # detailed per-portion breakdown

    if mode == "partials":
        # Track how much has been exited per portion
        portion_exited = {1: 0, 2: 0, 3: 0}
        for e in executions:
            portion_exited[e["portion"]] = portion_exited.get(e["portion"], 0) + e["qty"]

        # Build lookup for levels
        portion_levels = {}
        for lv in levels:
            key = (lv["level_type"], lv["portion"])
            portion_levels[key] = lv

        total_stop_risk = 0  # raw risk from stops (can be negative = locked profit)
        total_reward = 0

        for p in [1, 2, 3]:
            stop_lv = portion_levels.get(("stop", p))
            tp_lv   = portion_levels.get(("tp", p))
            if not stop_lv:
                continue

            orig_qty = stop_lv["qty"]
            exited = portion_exited.get(p, 0)
            rem = orig_qty - exited
            if rem <= 0:
                continue

            # Calculate stop outcome: what happens if stopped out
            # For Long: stop below entry = loss, stop above entry = locked profit
            # For Short: stop above entry = loss, stop below entry = locked profit
            if is_long:
                stop_pnl = (stop_lv["price"] - entry_price) * rem * dpp
            else:
                stop_pnl = (entry_price - stop_lv["price"]) * rem * dpp

            # stop_pnl < 0 means risk (loss if stopped)
            # stop_pnl > 0 means locked profit (trailing stop past entry)
            total_stop_risk += stop_pnl

            # Reward from TP
            if tp_lv:
                if is_long:
                    tp_pnl = (tp_lv["price"] - entry_price) * rem * dpp
                else:
                    tp_pnl = (entry_price - tp_lv["price"]) * rem * dpp
                total_reward += max(tp_pnl, 0)
            else:
                tp_pnl = 0

            portion_details.append({
                "portion": p, "qty": rem,
                "stop_price": stop_lv["price"],
                "tp_price": tp_lv["price"] if tp_lv else None,
                "stop_pnl": round(stop_pnl, 2),  # negative=risk, positive=locked profit
                "tp_pnl": round(tp_pnl, 2),
            })

        # Net worst case = what happens if ALL remaining portions get stopped
        # plus what we've already realized
        worst_case_pnl = total_stop_risk + realized_pnl
        # Current risk = how much we could lose from HERE (negative = at risk, positive = net profitable even if stopped)
        # For display: current_risk is the absolute downside from current state
        if worst_case_pnl < 0:
            current_risk = abs(worst_case_pnl)
        else:
            current_risk = 0  # we're in profit even if stopped everywhere

        net_stop_exposure = round(worst_case_pnl, 2)

    else:
        # Full mode
        total_reward = 0
        net_stop_exposure = 0

        if remaining_qty > 0:
            stop_lv = next((lv for lv in levels if lv["level_type"] == "stop"), None)
            tp_lv   = next((lv for lv in levels if lv["level_type"] == "tp"), None)

            if stop_lv:
                if is_long:
                    stop_pnl = (stop_lv["price"] - entry_price) * remaining_qty * dpp
                else:
                    stop_pnl = (entry_price - stop_lv["price"]) * remaining_qty * dpp

                worst_case = stop_pnl + realized_pnl
                if worst_case < 0:
                    current_risk = abs(worst_case)
                else:
                    current_risk = 0
                net_stop_exposure = round(worst_case, 2)
            else:
                current_risk = 0

            if tp_lv:
                if is_long:
                    tp_pnl = (tp_lv["price"] - entry_price) * remaining_qty * dpp
                else:
                    tp_pnl = (entry_price - tp_lv["price"]) * remaining_qty * dpp
                total_reward = max(tp_pnl, 0)

        portion_details = []

    return {
        "remaining_qty":    remaining_qty,
        "exited_qty":       exited_qty,
        "realized_pnl":     round(realized_pnl, 2),
        "current_risk":     round(current_risk, 2),
        "potential_reward":  round(total_reward, 2),
        "initial_risk":     round(initial_risk, 2),
        "net_stop_exposure": net_stop_exposure,  # negative = net loss if all stopped, positive = net profit even if stopped
        "active_portions":  [p for p in portion_details if p["qty"] > 0] if mode == "partials" else [],
        "portion_details":  portion_details,
        "is_closed":        remaining_qty <= 0,
    }


def close_live_trade_to_journal(live_trade_id):
    """
    Explicitly save a live trade to the journal.
    Called by user clicking "Save & Push to Journal".
    Trade does NOT need to be fully closed — user decides when to push.
    """
    import json
    from datetime import date as dt_date

    lt = db.get_live_trade(live_trade_id)
    if not lt:
        return None

    calc = recalculate_live_trade(lt)

    today = dt_date.today().isoformat()
    portfolio_id = lt.get("portfolio_id")

    # Find or create trading day
    existing_day = db.get_day_by_date_portfolio(today, portfolio_id)
    if existing_day:
        day_id = existing_day["id"]
    else:
        day_id = db.upsert_day(today, portfolio_id)

    # Determine next trade_num for this day
    with db.get_conn() as conn:
        max_num = conn.execute(
            "SELECT COALESCE(MAX(trade_num), 0) FROM trades WHERE day_id = ?", (day_id,)
        ).fetchone()[0]

    trade_num = max_num + 1

    # Compute avg exit from executions
    executions = lt.get("executions", [])
    total_exit_val = sum(e["price"] * e["qty"] for e in executions)
    total_exit_qty = sum(e["qty"] for e in executions)
    avg_exit = round(total_exit_val / total_exit_qty, 4) if total_exit_qty else lt["entry_price"]

    # Get last execution time
    exit_time = executions[-1]["exec_time"] if executions else lt["entry_time"]

    realized_pnl = calc["realized_pnl"]

    trade_id = db.insert_trade(
        day_id, trade_num, lt["direction"], lt["total_qty"],
        lt["entry_price"], avg_exit, realized_pnl,
        lt["entry_time"], exit_time, is_open=(calc["remaining_qty"] > 0)
    )

    # Save tags from live trade
    try:
        tags = json.loads(lt.get("tags_json", "{}"))
        for group_id, tag_list in tags.items():
            db.set_trade_tags(trade_id, group_id, tag_list)
    except (json.JSONDecodeError, AttributeError):
        pass

    # Save notes
    if lt.get("notes"):
        db.update_trade_notes(trade_id, lt["notes"])

    # Generate fills from entry + executions
    # The entry is one fill (Buy for Long, Sell for Short)
    entry_side = "Buy" if lt["direction"] == "Long" else "Sell"
    db.insert_fill(trade_id, lt["entry_time"], entry_side, lt["total_qty"], lt["entry_price"])

    # Each execution is a fill on the opposite side
    exit_side = "Sell" if lt["direction"] == "Long" else "Buy"
    for e in executions:
        db.insert_fill(trade_id, e["exec_time"], exit_side, e["qty"], e["price"])

    # Mark live trade as closed and link to journal
    db.update_live_trade(live_trade_id,
                         status="closed",
                         closed_at=dt_date.today().isoformat(),
                         realized_pnl=realized_pnl,
                         journal_trade_id=trade_id)

    return trade_id
