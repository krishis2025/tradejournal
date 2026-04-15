"""
HTTP / PRESENTATION LAYER
Flask routes only. Delegates all logic to app_logic.py and database.py.
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory
from datetime import date, timedelta
from werkzeug.utils import secure_filename
import database as db
import app_logic as logic
import json, os, uuid

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB

IMAGES_DIR = os.path.join(os.path.dirname(__file__), "data", "images")

ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


@app.before_request
def _ensure_db():
    db.init_db()
    os.makedirs(IMAGES_DIR, exist_ok=True)


@app.context_processor
def inject_obs_categories():
    return {
        "obs_categories": logic.get_observation_categories(),
        "obs_groups": logic.get_observation_groups(),
    }


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    today        = date.today()
    preset       = request.args.get("preset", "all")

    # Resolve preset to date range server-side
    if preset == "month":
        default_from = today.replace(day=1).isoformat()
        default_to   = today.isoformat()
    elif preset == "week":
        default_from = (today - timedelta(days=today.weekday())).isoformat()
        default_to   = today.isoformat()
    elif preset == "90d":
        default_from = (today - timedelta(days=90)).isoformat()
        default_to   = today.isoformat()
    elif preset == "30d":
        default_from = (today - timedelta(days=30)).isoformat()
        default_to   = today.isoformat()
    elif preset == "all":
        default_from = "2000-01-01"
        default_to   = "2099-12-31"
    else:
        default_from = "2000-01-01"
        default_to   = "2099-12-31"

    date_from = request.args.get("from",   default_from)
    date_to   = request.args.get("to",     default_to)

    # Account comes from query string (set by nav JS via page reload)
    account_id = request.args.get("account") or None

    days = db.get_all_days(date_from, date_to, account_id)

    for day in days:
        day_trades = db.get_trades_for_day(day["id"])
        day["grade_pct"] = logic.compute_combined_day_score(day.get("day_score", ""), day_trades)

    # Build calendar data from existing days list
    calendar_data = [
        {"date": d["date"], "pnl": d["total_pnl"] or 0, "trades": d["trade_count"], "wins": d["wins"] or 0}
        for d in days
    ]

    return render_template(
        "index.html",
        days=days,
        date_from=date_from,
        date_to=date_to,
        account_id=account_id,
        preset=preset,
        today=today.isoformat(),
        calendar_json=json.dumps(calendar_data),
    )


@app.route("/day/<int:day_id>")
def day_view(day_id):
    day = db.get_day_by_id(day_id)
    if not day:
        return render_template("404.html", message=f"Day #{day_id} not found"), 404
    trades = db.get_trades_for_day(day_id)
    for trade in trades:
        ctx_id = trade.get("context_id")
        if ctx_id:
            ctx = db.get_developing_context_by_id(ctx_id)
            if ctx:
                # Convert 24h time to 12h format
                try:
                    h, m = ctx["time"].split(":")
                    h = int(h)
                    ampm = "AM" if h < 12 else "PM"
                    h = h % 12 or 12
                    ctx["time_12h"] = f"{h}:{m} {ampm}"
                except (ValueError, KeyError):
                    ctx["time_12h"] = ctx.get("time", "")
                # Shortened value area + color
                va = ctx.get("value_state", "") or ctx.get("value_area", "")
                va_map = {
                    "Lower": ("Lower", "red"),
                    "Overlapping Lower": ("Ovlp Lower", "blue"),
                    "Overlapping": ("Overlapping", "blue"),
                    "Overlapping Higher": ("Ovlp Higher", "blue"),
                    "Higher": ("Higher", "green"),
                    "Balanced": ("Balanced", "blue"),
                }
                ctx["value_area_short"], ctx["val_color"] = va_map.get(va, (va, "blue"))
                trade["context"] = ctx
            else:
                trade["context"] = None
        else:
            trade["context"] = None
    day_images = db.get_day_images(day_id)
    observations = db.get_observations_for_date(day["date"])
    return render_template(
        "day.html",
        day=day,
        trades=trades,
        day_images=day_images,
        observations=observations,
        observation_categories=logic.get_observation_categories(),
        tag_groups=logic.get_tag_groups(),
        tags_json=json.dumps(logic.get_tag_groups()),
        day_type_tags=logic.get_day_type_tags(),
        day_value_tags=logic.get_day_value_tags(),
        day_volume_tags=logic.get_day_volume_tags(),
        grade_pct=logic.compute_combined_day_score(day.get("day_score", ""), trades),
    )


@app.route("/day/<date_str>")
def day_view_by_date(date_str):
    day = db.get_day_by_date(date_str)
    if not day:
        return render_template("404.html", message=f"No data for {date_str}"), 404
    return redirect(url_for("day_view", day_id=day["id"]))


@app.route("/trade/<int:trade_id>")
def trade_view(trade_id):
    trade = db.get_trade_by_id(trade_id)
    if not trade:
        return render_template("404.html", message=f"Trade #{trade_id} not found"), 404
    # Parse execution_json if present (from live trade push)
    exec_detail = None
    if trade.get("execution_json"):
        try:
            exec_detail = json.loads(trade["execution_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    return render_template(
        "trade.html",
        trade=trade,
        exec_detail=exec_detail,
        exec_detail_json=json.dumps(exec_detail) if exec_detail else 'null'
    )


@app.route("/trade/<int:trade_id>/v2")
def trade_view_v2(trade_id):
    trade = db.get_trade_by_id(trade_id)
    if not trade:
        return render_template("404.html", message=f"Trade #{trade_id} not found"), 404

    # Parse execution_json for the focused trade
    exec_detail = None
    if trade.get("execution_json"):
        try:
            exec_detail = json.loads(trade["execution_json"])
        except (json.JSONDecodeError, TypeError):
            pass

    # Parse execution_score_json for the focused trade
    exec_score = None
    if trade.get("execution_score_json"):
        try:
            exec_score = json.loads(trade["execution_score_json"])
        except (json.JSONDecodeError, TypeError):
            pass

    # Load all sibling trades for the same day
    siblings_raw = db.get_trades_for_day(trade["day_id"])
    siblings = []
    context_ids = set()
    for st in siblings_raw:
        sib = {
            "id": st["id"],
            "trade_num": st["trade_num"],
            "direction": st.get("direction"),
            "qty": st.get("qty"),
            "avg_entry": st.get("avg_entry"),
            "pnl": st.get("pnl"),
            "is_open": st.get("is_open"),
            "entry_time": st.get("entry_time"),
            "context_id": st.get("context_id"),
            "exec_detail": None,
            "exec_score": None,
        }
        if st.get("execution_json"):
            try:
                sib["exec_detail"] = json.loads(st["execution_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        if st.get("execution_score_json"):
            try:
                sib["exec_score"] = json.loads(st["execution_score_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        if st.get("context_id"):
            context_ids.add(st["context_id"])
        siblings.append(sib)

    # Load all unique contexts
    contexts = {}
    for cid in context_ids:
        ctx = db.get_developing_context_by_id(cid)
        if ctx:
            contexts[cid] = ctx

    return render_template(
        "trade_v2.html",
        trade=trade,
        exec_detail=exec_detail,
        exec_detail_json=json.dumps(exec_detail) if exec_detail else "null",
        exec_score_json=json.dumps(exec_score) if exec_score else "null",
        siblings_json=json.dumps(siblings),
        contexts_json=json.dumps(contexts),
    )


@app.route("/analytics")
def analytics():
    account_id = request.args.get("account") or None
    date_from    = request.args.get("date_from") or None
    date_to      = request.args.get("date_to") or None
    date_preset  = request.args.get("preset") or "all"

    # Resolve presets to actual dates
    if date_preset != "all" and date_preset != "custom":
        from datetime import date, timedelta
        today = date.today()
        if date_preset == "week":
            date_from = (today - timedelta(days=today.weekday())).isoformat()
            date_to = today.isoformat()
        elif date_preset == "month":
            date_from = today.replace(day=1).isoformat()
            date_to = today.isoformat()
        elif date_preset == "30d":
            date_from = (today - timedelta(days=30)).isoformat()
            date_to = today.isoformat()
        elif date_preset == "90d":
            date_from = (today - timedelta(days=90)).isoformat()
            date_to = today.isoformat()

    data         = db.get_analytics(account_id=account_id, date_from=date_from, date_to=date_to)
    accounts     = db.get_all_accounts()
    return render_template(
        "analytics.html",
        data=data,
        data_json=json.dumps(data),
        accounts=accounts,
        account_id=account_id,
        date_from=date_from or "",
        date_to=date_to or "",
        date_preset=date_preset,
    )


@app.route("/accounts")
def accounts_view_manage():
    return render_template("accounts.html", accounts=db.get_all_accounts())


@app.route("/simulation")
def simulation_view():
    summaries = db.get_all_account_summaries()
    return render_template("simulation.html", summaries=summaries)


@app.route("/settings")
def settings_view():
    tag_groups = logic.get_tag_groups()
    defaults   = logic.TAG_GROUPS
    trade_defaults = logic.get_trade_defaults()
    instrument_config = logic.get_instrument_config()
    accounts = db.get_all_accounts()
    # Build obs category group with current (possibly custom) tags
    obs_cat_group = dict(logic.OBS_CATEGORY_GROUP)
    obs_cat_group["tags"] = logic.get_observation_categories()
    # Build obs group group with current (possibly custom) tags
    obs_group_group = dict(logic.OBS_GROUP_GROUP)
    obs_group_group["tags"] = logic.get_observation_groups()
    # Build day marker groups
    day_type_group = dict(logic.DAY_TYPE_GROUP)
    day_type_group["tags"] = logic.get_day_type_tags()
    day_value_group = dict(logic.DAY_VALUE_GROUP)
    day_value_group["tags"] = logic.get_day_value_tags()
    day_volume_group = dict(logic.DAY_VOLUME_GROUP)
    day_volume_group["tags"] = logic.get_day_volume_tags()
    # Build grade categories group
    grade_cat_group = dict(logic.DAY_GRADE_GROUP)
    grade_cat_group["tags"] = logic.get_grade_categories()
    all_defaults = defaults + [logic.OBS_CATEGORY_GROUP, logic.OBS_GROUP_GROUP,
                               logic.DAY_TYPE_GROUP, logic.DAY_VALUE_GROUP, logic.DAY_VOLUME_GROUP,
                               logic.DAY_GRADE_GROUP]
    return render_template(
        "settings.html",
        tag_groups=tag_groups,
        defaults=defaults,
        defaults_json=json.dumps(all_defaults),
        tag_groups_json=json.dumps(tag_groups),
        obs_cat_group=obs_cat_group,
        obs_group_group=obs_group_group,
        day_type_group=day_type_group,
        day_value_group=day_value_group,
        day_volume_group=day_volume_group,
        grade_cat_group=grade_cat_group,
        trade_defaults=trade_defaults,
        instrument_config=instrument_config,
        accounts=accounts,
        accounts_json=json.dumps(accounts),
        signals=db.get_all_signals(),
        signals_json=json.dumps(db.get_all_signals()),
        headline_helpers=db.get_all_headline_helpers(),
    )


@app.route("/live")
def live_trade_page():
    """New Ticket UI — single-page live trade interface with date range filter."""
    from datetime import date as dt_date, timedelta

    # Parse date range from query params
    range_key = request.args.get("range", "today")
    custom_from = request.args.get("from", "")
    custom_to = request.args.get("to", "")

    today = dt_date.today()
    if range_key == "today":
        date_from = date_to = today.isoformat()
    elif range_key == "yesterday":
        yd = today - timedelta(days=1)
        date_from = date_to = yd.isoformat()
    elif range_key == "week":
        date_from = (today - timedelta(days=7)).isoformat()
        date_to = today.isoformat()
    elif range_key == "month":
        date_from = (today - timedelta(days=30)).isoformat()
        date_to = today.isoformat()
    elif range_key == "custom" and custom_from and custom_to:
        date_from = custom_from
        date_to = custom_to
    else:
        date_from = date_to = today.isoformat()

    account_id = request.args.get("account")
    open_trades  = db.get_all_live_trades(status="open", date_from=date_from, date_to=date_to, account_id=account_id)
    closed_trades = db.get_all_live_trades(status="closed", date_from=date_from, date_to=date_to, account_id=account_id)

    # Pre-compute calc for each trade (open and closed)
    for t in open_trades + closed_trades:
        full = db.get_live_trade(t["id"])
        t["levels"] = full.get("levels", [])
        t["executions"] = full.get("executions", [])
        t["calc"] = logic.recalculate_live_trade(full)

    contexts = db.get_developing_contexts(date_from, date_to, account_id)

    return render_template(
        "live_ticket.html",
        open_trades=open_trades,
        closed_trades=closed_trades,
        tag_groups=logic.get_tag_groups(),
        tags_json=json.dumps(logic.get_tag_groups()),
        trade_defaults=logic.get_trade_defaults(),
        trade_defaults_json=json.dumps(logic.get_trade_defaults()),
        instrument_config_json=json.dumps(logic.get_instrument_config()),
        active_range=range_key,
        date_from=date_from,
        date_to=date_to,
        contexts=contexts,
        contexts_json=json.dumps(contexts),
    )


@app.route("/live-v2")
def live_trade_v2_page():
    """Ladder-based trade companion tool — phase-driven UI."""
    from datetime import date as dt_date
    today = dt_date.today()
    date_from = date_to = today.isoformat()
    account_id = request.args.get("account") or None

    open_trades = db.get_all_live_trades(status="open", date_from=date_from, date_to=date_to, account_id=account_id)
    closed_trades = db.get_all_live_trades(status="closed", date_from=date_from, date_to=date_to, account_id=account_id)

    for t in open_trades + closed_trades:
        full = db.get_live_trade(t["id"])
        t["levels"] = full.get("levels", [])
        t["executions"] = full.get("executions", [])
        t["calc"] = logic.recalculate_live_trade(full)

    contexts = db.get_developing_contexts(date_from, date_to, account_id)

    # Attach signals and legs to each context
    for ctx in contexts:
        ctx["signals"] = db.get_market_signals_by_context(ctx["id"])
        ctx["legs"] = db.get_trade_plan_legs_by_context(ctx["id"])

    # Build strength lookup for trades that have a strength_id
    strength_map = {}
    for t in open_trades + closed_trades:
        sid = t.get("strength_id")
        if sid and sid not in strength_map:
            s = db.get_trade_strength(sid)
            if s:
                strength_map[sid] = s

    # Signal library for context form dropdown
    signal_library = db.get_all_signals()

    return render_template("live_v2.html",
        open_trades=open_trades, closed_trades=closed_trades,
        contexts=contexts, contexts_json=json.dumps(contexts),
        tags_json=json.dumps(logic.get_tag_groups()),
        trade_defaults_json=json.dumps(logic.get_trade_defaults()),
        instrument_config_json=json.dumps(logic.get_instrument_config()),
        open_trades_json=json.dumps(open_trades),
        closed_trades_json=json.dumps(closed_trades),
        strength_json=json.dumps(strength_map),
        signal_library_json=json.dumps(signal_library),
    )


# ── Legacy Live Trade routes (fully functional, accessible at /live-legacy) ──

@app.route("/live-legacy")
def live_trade_list_legacy():
    open_trades  = db.get_all_live_trades(status="open")
    closed_trades = db.get_all_live_trades(status="closed")
    return render_template(
        "live_list_legacy.html",
        open_trades=open_trades,
        closed_trades=closed_trades,
    )


@app.route("/live-legacy/new")
def live_trade_new_legacy():
    account_id = request.args.get("account") or None
    return render_template(
        "live_entry_legacy.html",
        trade=None,
        tag_groups=logic.get_tag_groups(),
        tags_json=json.dumps(logic.get_tag_groups()),
        trade_defaults=logic.get_trade_defaults(),
        instrument_config_json=json.dumps(logic.get_instrument_config()),
        account_id=account_id,
    )


@app.route("/live-legacy/<int:live_trade_id>")
def live_trade_view_legacy(live_trade_id):
    trade = db.get_live_trade(live_trade_id)
    if not trade:
        return render_template("404.html", message=f"Live trade #{live_trade_id} not found"), 404
    calc = logic.recalculate_live_trade(trade)
    return render_template(
        "live_entry_legacy.html",
        trade=trade,
        calc=calc,
        calc_json=json.dumps(calc),
        tag_groups=logic.get_tag_groups(),
        tags_json=json.dumps(logic.get_tag_groups()),
        trade_defaults=logic.get_trade_defaults(),
        instrument_config_json=json.dumps(logic.get_instrument_config()),
        account_id=trade.get("account_id") or None,
    )


# ── Serve saved images ────────────────────────────────────────────────────────

@app.route("/images/<path:filename>")
def serve_image(filename):
    return send_from_directory(IMAGES_DIR, filename)


# ── API: Import ───────────────────────────────────────────────────────────────

@app.route("/api/import", methods=["POST"])
def api_import():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400
    account_id = request.form.get("account_id") or None
    if account_id:
        account_id = int(account_id)
    try:
        result = logic.import_file(f.filename, f.read(), account_id)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500


# ── API: Trading Days ─────────────────────────────────────────────────────────

@app.route("/api/day/create", methods=["POST"])
def api_create_day():
    data = request.json or {}
    date_str = data.get("date")
    account_id = data.get("account_id") or None
    if not date_str:
        return jsonify(error="Date is required"), 400
    existing = db.get_day_by_date_account(date_str, account_id)
    created = existing is None
    day_id = db.upsert_day(date_str, account_id)
    return jsonify(day_id=day_id, created=created)


@app.route("/api/day/<int:day_id>", methods=["DELETE"])
def api_delete_day(day_id):
    day = db.get_day_by_id(day_id)
    if not day:
        return jsonify({"error": "Day not found"}), 404
    try:
        db.delete_day(day_id)
        return jsonify({"ok": True, "deleted": day_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: Trades ───────────────────────────────────────────────────────────────

@app.route("/api/trade/<int:trade_id>/tags", methods=["POST"])
def api_save_tags(trade_id):
    body     = request.get_json(silent=True) or {}
    group_id = body.get("group_id")
    tags     = body.get("tags", [])
    if not group_id:
        return jsonify({"error": "group_id required"}), 400
    db.set_trade_tags(trade_id, group_id, tags)
    return jsonify({"ok": True})


@app.route("/api/trade/<int:trade_id>/notes", methods=["POST"])
def api_save_notes(trade_id):
    body  = request.get_json(silent=True) or {}
    notes = body.get("notes", "")
    notes_monitoring = body.get("notes_monitoring")
    notes_exit = body.get("notes_exit")
    db.update_trade_notes(trade_id, notes, notes_monitoring, notes_exit)
    return jsonify({"ok": True})


# ── API: Images ───────────────────────────────────────────────────────────────

@app.route("/api/trade/<int:trade_id>/images", methods=["POST"])
def api_upload_image(trade_id):
    if "image" not in request.files:
        return jsonify({"error": "No image file"}), 400
    f = request.files["image"]
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        return jsonify({"error": f"File type {ext} not allowed. Use JPG, PNG, GIF or WebP."}), 422

    # Save with a unique name to avoid collisions
    unique_name = f"trade_{trade_id}_{uuid.uuid4().hex[:8]}{ext}"
    f.save(os.path.join(IMAGES_DIR, unique_name))

    caption  = request.form.get("caption", "")
    image_id = db.add_trade_image(trade_id, unique_name, caption)

    return jsonify({
        "ok":      True,
        "id":      image_id,
        "url":     f"/images/{unique_name}",
        "caption": caption,
    })


@app.route("/api/image/<int:image_id>/caption", methods=["POST"])
def api_update_caption(image_id):
    body    = request.get_json(silent=True) or {}
    caption = body.get("caption", "")
    db.update_image_caption(image_id, caption)
    return jsonify({"ok": True})


@app.route("/api/image/<int:image_id>", methods=["DELETE"])
def api_delete_image(image_id):
    filename = db.delete_trade_image(image_id)
    if filename:
        path = os.path.join(IMAGES_DIR, filename)
        if os.path.exists(path):
            os.remove(path)
    return jsonify({"ok": True})


# ── API: Accounts ────────────────────────────────────────────────────────────

@app.route("/api/account", methods=["POST"])
def api_create_account():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Account name is required"}), 400
    try:
        aid = db.create_account(
            name, body.get("description", ""), body.get("color", "#4fffb0"),
            account_size=float(body["account_size"]) if body.get("account_size") else None,
            default_qty=int(body["default_qty"]) if body.get("default_qty") else None,
            default_instrument=body.get("default_instrument") or None,
            is_primary=1 if body.get("is_primary") else 0,
            risk_per_trade_pct=float(body["risk_per_trade_pct"]) if body.get("risk_per_trade_pct") else None,
        )
        return jsonify({"ok": True, "id": aid})
    except Exception as e:
        return jsonify({"error": str(e)}), 422


@app.route("/api/account/<int:account_id>", methods=["PUT"])
def api_update_account(account_id):
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Account name is required"}), 400
    db.update_account(
        account_id, name, body.get("description", ""), body.get("color", "#4fffb0"),
        account_size=float(body["account_size"]) if body.get("account_size") else None,
        default_qty=int(body["default_qty"]) if body.get("default_qty") else None,
        default_instrument=body.get("default_instrument") or None,
        is_primary=1 if body.get("is_primary") else 0,
        risk_per_trade_pct=float(body["risk_per_trade_pct"]) if body.get("risk_per_trade_pct") else None,
    )
    return jsonify({"ok": True})


@app.route("/api/account/<int:account_id>", methods=["DELETE"])
def api_delete_account(account_id):
    try:
        db.delete_account(account_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/accounts")
def api_accounts():
    return jsonify(db.get_all_accounts())


@app.route("/api/shadow/regenerate", methods=["POST"])
def api_regenerate_shadows():
    count = logic.regenerate_all_shadows()
    return jsonify({"ok": True, "trades_processed": count})


@app.route("/api/settings/theme", methods=["POST"])
def api_save_theme():
    body = request.get_json(silent=True) or {}
    theme = body.get("theme", "mint")
    db.set_config("theme", theme)
    return jsonify({"ok": True})


@app.route("/api/settings/theme", methods=["GET"])
def api_get_theme():
    config = db.get_all_config()
    return jsonify({"theme": config.get("theme", "mint")})


# ── API: Analytics ────────────────────────────────────────────────────────────

@app.route("/api/analytics")
def api_analytics():
    account_id = request.args.get("account") or None
    return jsonify(db.get_analytics(account_id=account_id))


# ── API: DB Admin ─────────────────────────────────────────────────────────────

@app.route("/api/db/export")
def api_db_export():
    """Dump entire database as a SQL script."""
    import sqlite3, io
    from flask import Response
    from datetime import datetime
    conn = sqlite3.connect(db.DB_PATH)
    buf  = io.StringIO()
    buf.write(f"-- Trade Journal export\n-- Generated: {datetime.now().isoformat()}\n\n")
    for line in conn.iterdump():
        buf.write(line + "\n")
    conn.close()
    sql = buf.getvalue()
    return Response(
        sql,
        mimetype="text/plain",
        headers={"Content-Disposition": "attachment; filename=tradejournal_backup.sql"}
    )


@app.route("/api/db/import", methods=["POST"])
def api_db_import():
    """Restore database from an uploaded SQL script."""
    import sqlite3, os, shutil
    from datetime import datetime
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f.filename.endswith(".sql"):
        return jsonify({"error": "Please upload a .sql file"}), 422

    sql_text = f.read().decode("utf-8")

    # Safety: back up current db before overwriting
    backup_path = db.DB_PATH + f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if os.path.exists(db.DB_PATH):
        shutil.copy2(db.DB_PATH, backup_path)

    try:
        # Delete existing DB file and recreate from the SQL dump
        import tempfile
        # Write SQL to a temp db first to validate it works
        temp_path = db.DB_PATH + ".import_tmp"
        if os.path.exists(temp_path):
            os.remove(temp_path)
        conn = sqlite3.connect(temp_path)
        conn.executescript(sql_text)
        conn.close()

        # Success — replace the real DB
        if os.path.exists(db.DB_PATH):
            os.remove(db.DB_PATH)
        shutil.move(temp_path, db.DB_PATH)

        return jsonify({"ok": True, "message": "Database restored successfully."})
    except Exception as e:
        # Restore backup on failure
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, db.DB_PATH)
        return jsonify({"error": f"Import failed: {e}"}), 500

@app.route("/api/settings/tags/<group_id>", methods=["POST"])
def api_save_tag_config(group_id):
    body = request.get_json(silent=True) or {}
    tags = body.get("tags", [])
    if not isinstance(tags, list):
        return jsonify({"error": "tags must be a list"}), 400
    db.save_tag_config(group_id, [t for t in tags if t.strip()])
    return jsonify({"ok": True, "group_id": group_id, "tags": tags})


@app.route("/api/settings/tags/<group_id>/reset", methods=["POST"])
def api_reset_tag_config(group_id):
    db.reset_tag_config(group_id)
    if group_id == "obs_categories":
        return jsonify({"ok": True, "tags": logic.OBSERVATION_CATEGORIES})
    if group_id == "obs_groups":
        return jsonify({"ok": True, "tags": logic.OBSERVATION_GROUPS})
    if group_id == "day_type":
        return jsonify({"ok": True, "tags": logic.DAY_TYPE_TAGS})
    if group_id == "day_value":
        return jsonify({"ok": True, "tags": logic.DAY_VALUE_TAGS})
    if group_id == "day_volume":
        return jsonify({"ok": True, "tags": logic.DAY_VOLUME_TAGS})
    group = next((g for g in logic.TAG_GROUPS if g["id"] == group_id), None)
    return jsonify({"ok": True, "tags": group["tags"] if group else []})


@app.route("/api/settings/tags", methods=["GET"])
def api_get_tag_config():
    return jsonify(logic.get_tag_groups())


# ── API: Trade Defaults & Instrument Config ──────────────────────────────────

@app.route("/api/settings/trade-defaults", methods=["POST"])
def api_save_trade_defaults():
    body = request.get_json(silent=True) or {}
    for key in logic.DEFAULT_TRADE_DEFAULTS:
        if key in body:
            db.set_config(f"td_{key}", body[key])
    return jsonify({"ok": True})


@app.route("/api/settings/instruments", methods=["POST"])
def api_save_instrument_config():
    body = request.get_json(silent=True) or {}
    for inst in ["MES", "ES"]:
        if inst in body:
            cfg = body[inst]
            if "dollars_per_point" in cfg:
                db.set_config(f"inst_{inst}_dpp", cfg["dollars_per_point"])
            if "dollars_per_tick" in cfg:
                db.set_config(f"inst_{inst}_dpt", cfg["dollars_per_tick"])
            if "ticks_per_point" in cfg:
                db.set_config(f"inst_{inst}_tpp", cfg["ticks_per_point"])
    return jsonify({"ok": True})


# ── API: Signal Library ──────────────────────────────────────────────────────

@app.route("/api/signals", methods=["GET"])
def api_get_signals():
    return jsonify(db.get_all_signals())


@app.route("/api/signals", methods=["POST"])
def api_create_signal():
    body = request.get_json(silent=True) or {}
    signal_key = body.get("signal_key", "").strip()
    signal_value = body.get("signal_value", "").strip()
    if not signal_key or not signal_value:
        return jsonify({"ok": False, "error": "signal_key and signal_value required"}), 400
    try:
        sid = db.create_signal(
            signal_key=signal_key,
            signal_value=signal_value,
            default_polarity=body.get("default_polarity", "neutral"),
        )
        return jsonify({"ok": True, "id": sid})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/signals/<int:signal_id>", methods=["PATCH"])
def api_update_signal(signal_id):
    body = request.get_json(silent=True) or {}
    db.update_signal(signal_id, **body)
    return jsonify({"ok": True})


@app.route("/api/signals/<int:signal_id>", methods=["DELETE"])
def api_delete_signal(signal_id):
    db.delete_signal(signal_id)
    return jsonify({"ok": True})


# ── API: Developing Context ───────────────────────────────────────────────────

@app.route("/api/context", methods=["POST"])
def api_create_context():
    body = request.get_json(silent=True) or {}

    # New fields
    day_type = body.get("day_type", "")
    volume_state = body.get("volume_state", "") or body.get("volume_read", "")
    HTF_Trend = body.get("HTF_Trend", "") or body.get("trend", "")
    observation = body.get("observation", "")
    plan_text = body.get("plan_text", "")
    plan_location = body.get("plan_location", "")
    plan_trigger = body.get("plan_trigger", "")
    nuances_json = body.get("nuances_json", "[]")
    market_story = body.get("market_story", "") or body.get("notes", "")
    headline_read = body.get("headline_read", "")
    confidence_score = body.get("confidence_score", "")
    bias_direction = body.get("bias_direction", "")
    execution_headline = body.get("execution_headline", "")

    # Backfill old fields from new fields for backward compat
    mkt_read = body.get("mkt_read", "") or day_type
    setup = body.get("setup", "") or plan_text
    location = body.get("location", "") or plan_location
    nuance = body.get("nuance", "") or market_story or observation

    ctx_id = db.create_developing_context(
        account_id=body.get("account_id") or None,
        date=body.get("date", ""),
        time=body.get("time", ""),
        mkt_read=mkt_read,
        value_state=body.get("value_state", "") or body.get("value_area", ""),
        setup=setup,
        location=location,
        nuance=nuance,
        mental_state=body.get("mental_state", "calm"),
        day_type=day_type,
        volume_state=volume_state,
        HTF_Trend=HTF_Trend,
        observation=observation,
        plan_text=plan_text,
        plan_location=plan_location,
        plan_trigger=plan_trigger,
        nuances_json=nuances_json,
        market_story=market_story,
        headline_read=headline_read,
        confidence_score=confidence_score,
        bias_direction=bias_direction,
        execution_headline=execution_headline,
    )
    return jsonify({"ok": True, "id": ctx_id})


@app.route("/api/context/<int:ctx_id>", methods=["PATCH"])
def api_update_context(ctx_id):
    body = request.get_json(silent=True) or {}
    db.update_developing_context(ctx_id, **body)
    return jsonify({"ok": True})


# ── API: Context Signals & Legs ──────────────────────────────────────────────

@app.route("/api/context/<int:ctx_id>/signals", methods=["GET"])
def api_get_context_signals(ctx_id):
    rows = db.get_market_signals_by_context(ctx_id)
    return jsonify(rows)


@app.route("/api/context/<int:ctx_id>/signals", methods=["POST"])
def api_create_context_signals(ctx_id):
    body = request.get_json(silent=True) or {}
    signals = body.get("signals", [])
    created = []
    for s in signals:
        sid = db.create_market_signal(ctx_id, s.get("signal_value", ""), s.get("signal_polarity", "neutral"))
        created.append(sid)
    return jsonify({"ok": True, "ids": created})


@app.route("/api/context/<int:ctx_id>/legs", methods=["GET"])
def api_get_context_legs(ctx_id):
    rows = db.get_trade_plan_legs_by_context(ctx_id)
    return jsonify(rows)


@app.route("/api/context/<int:ctx_id>/legs", methods=["POST"])
def api_create_context_legs(ctx_id):
    body = request.get_json(silent=True) or {}
    legs = body.get("legs", [])
    created = []
    for i, leg in enumerate(legs):
        lid = db.create_trade_plan_leg(
            context_id=ctx_id,
            leg_type=leg.get("leg_type", ""),
            plan_label=leg.get("plan_label", ""),
            execution_side=leg.get("execution_side", ""),
            entry_zone_low=leg.get("entry_zone_low"),
            entry_zone_high=leg.get("entry_zone_high"),
            trigger_text=leg.get("trigger_text", ""),
            condition_text=leg.get("condition_text", ""),
            is_primary=leg.get("is_primary", 0),
            sort_order=leg.get("sort_order", i),
        )
        created.append(lid)
    return jsonify({"ok": True, "ids": created})


@app.route("/api/context/<int:ctx_id>/signals", methods=["DELETE"])
def api_delete_context_signals(ctx_id):
    db.delete_market_signals_by_context(ctx_id)
    return jsonify({"ok": True})


@app.route("/api/context/<int:ctx_id>/legs", methods=["DELETE"])
def api_delete_context_legs(ctx_id):
    db.delete_trade_plan_legs_by_context(ctx_id)
    return jsonify({"ok": True})


@app.route("/api/leg/<int:leg_id>", methods=["PATCH"])
def api_update_leg(leg_id):
    body = request.get_json(silent=True) or {}
    db.update_trade_plan_leg(leg_id, **body)
    return jsonify({"ok": True})


# ── API: Headline Helper ─────────────────────────────────────────────────────

@app.route("/api/headline-helpers", methods=["GET"])
def api_get_headline_helpers():
    rows = db.get_all_headline_helpers()
    return jsonify(rows)


@app.route("/api/headline-helpers/lookup", methods=["GET"])
def api_lookup_headline_helper():
    day_type = request.args.get("day_type", "")
    value_state = request.args.get("value_state", "")
    volume_state = request.args.get("volume_state", "")
    htf_trend = request.args.get("htf_trend", "")
    match = db.lookup_headline_helper(day_type, value_state, volume_state, htf_trend)
    if match:
        return jsonify({"ok": True, "match": match})
    return jsonify({"ok": False, "message": "No saved read for this scenario"})


@app.route("/api/headline-helpers", methods=["POST"])
def api_create_headline_helper():
    body = request.get_json(silent=True) or {}
    hid = db.create_headline_helper(
        day_type=body.get("day_type", ""),
        value_state=body.get("value_state", ""),
        volume_state=body.get("volume_state", ""),
        htf_trend=body.get("htf_trend", ""),
        headline_read=body.get("headline_read", ""),
        execution_headline=body.get("execution_headline", ""),
    )
    return jsonify({"ok": True, "id": hid})


@app.route("/api/headline-helpers/<int:hid>", methods=["DELETE"])
def api_delete_headline_helper(hid):
    db.delete_headline_helper(hid)
    return jsonify({"ok": True})


# ── API: Trade Strength ──────────────────────────────────────────────────────

@app.route("/api/trade-strength", methods=["POST"])
def api_create_trade_strength():
    body = request.get_json(silent=True) or {}
    try:
        strength_id = db.create_trade_strength(
            context_id=body.get("context_id") or None,
            account_id=body.get("account_id") or None,
            value=body.get("value", 0),
            volume=body.get("volume", 0),
            trend=body.get("trend", 0),
            mental_state=body.get("mental_state", "calm"),
            confidence=body.get("confidence", "medium"),
            adh=body.get("adh", 0),
        )
        return jsonify({"ok": True, "id": strength_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/trade-strength/<int:strength_id>", methods=["GET"])
def api_get_trade_strength(strength_id):
    row = db.get_trade_strength(strength_id)
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


# ── API: Live Trades ─────────────────────────────────────────────────────────

@app.route("/api/live", methods=["POST"])
def api_create_live_trade():
    body = request.get_json(silent=True) or {}
    required = ["direction", "instrument", "entry_price", "entry_time", "total_qty", "mode"]
    for key in required:
        if key not in body:
            return jsonify({"error": f"{key} is required"}), 400
    try:
        live_id = db.create_live_trade(
            account_id=body.get("account_id") or None,
            direction=body["direction"],
            instrument=body["instrument"],
            entry_price=float(body["entry_price"]),
            entry_time=body["entry_time"],
            total_qty=int(body["total_qty"]),
            mode=body["mode"],
            notes=body.get("notes", ""),
            tags_json=json.dumps(body.get("tags", {})),
            notes_monitoring=body.get("notes_monitoring", ""),
            notes_exit=body.get("notes_exit", ""),
            guard_json=json.dumps(body.get("guard", {})) if body.get("guard") else "",
            context_id=body.get("context_id") or None,
            strength_id=body.get("strength_id") or None,
        )
        # Compute and save default levels
        levels = logic.compute_live_trade_plan(
            body["direction"], body["instrument"],
            float(body["entry_price"]), int(body["total_qty"]), body["mode"]
        )
        db.set_live_trade_levels(live_id, levels)

        # Pin initial_risk at creation so the risk-left bar has a stable reference
        # (tightening a stop later must shrink the fill without shrinking the ghost).
        inst_cfg = logic.get_instrument_config().get(
            body["instrument"], logic.INSTRUMENT_CONFIG["MES"]
        )
        dpp = inst_cfg["dollars_per_point"]
        entry_price = float(body["entry_price"])
        initial_risk = 0.0
        for lv in levels:
            if lv.get("level_type") == "stop":
                initial_risk += abs(entry_price - lv["price"]) * lv["qty"] * dpp
        db.update_live_trade(live_id, initial_risk=round(initial_risk, 2))

        return jsonify({"ok": True, "id": live_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/live/<int:live_id>", methods=["GET"])
def api_get_live_trade(live_id):
    trade = db.get_live_trade(live_id)
    if not trade:
        return jsonify({"error": "Not found"}), 404
    return jsonify(trade)


@app.route("/api/live/<int:live_id>", methods=["PUT"])
def api_update_live_trade(live_id):
    body = request.get_json(silent=True) or {}
    allowed = {"notes", "notes_monitoring", "notes_exit", "tags_json", "status", "execution_score_json"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if "tags" in body:
        updates["tags_json"] = json.dumps(body["tags"])
    if updates:
        db.update_live_trade(live_id, **updates)
    return jsonify({"ok": True})


@app.route("/api/live/<int:live_id>", methods=["DELETE"])
def api_delete_live_trade(live_id):
    db.delete_live_trade(live_id)
    return jsonify({"ok": True})


@app.route("/api/live/<int:live_id>/levels", methods=["PUT"])
def api_update_live_levels(live_id):
    body = request.get_json(silent=True) or {}
    levels = body.get("levels", [])
    db.set_live_trade_levels(live_id, levels)
    trade = db.get_live_trade(live_id)
    calc = logic.recalculate_live_trade(trade)
    return jsonify({"ok": True, "calc": calc})


@app.route("/api/live/<int:live_id>/execute", methods=["POST"])
def api_live_execute(live_id):
    body = request.get_json(silent=True) or {}
    required = ["exec_type", "portion", "qty", "price", "exec_time"]
    for key in required:
        if key not in body:
            return jsonify({"error": f"{key} is required"}), 400

    trade = db.get_live_trade(live_id)
    if not trade:
        return jsonify({"error": "Trade not found"}), 404

    pnl = logic.compute_execution_pnl(
        trade["direction"], trade["instrument"],
        trade["entry_price"], float(body["price"]), int(body["qty"])
    )

    exec_id = db.add_live_trade_execution(
        live_id, body["exec_type"], int(body["portion"]),
        int(body["qty"]), float(body["price"]), body["exec_time"], pnl
    )

    # Recalculate
    trade = db.get_live_trade(live_id)
    calc = logic.recalculate_live_trade(trade)

    return jsonify({
        "ok": True, "exec_id": exec_id, "pnl": pnl,
        "calc": calc,
    })


@app.route("/api/live/<int:live_id>/push", methods=["POST"])
def api_live_push_to_journal(live_id):
    """Explicitly save live trade to journal and mark as closed."""
    trade = db.get_live_trade(live_id)
    if not trade:
        return jsonify({"error": "Trade not found"}), 404
    if trade.get("journal_trade_id"):
        return jsonify({"error": "Already pushed to journal"}), 422

    journal_trade_id = logic.close_live_trade_to_journal(live_id)
    if journal_trade_id:
        return jsonify({"ok": True, "journal_trade_id": journal_trade_id})
    else:
        return jsonify({"error": "Failed to push to journal"}), 500


@app.route("/api/live/<int:live_id>/execution/<int:exec_id>", methods=["DELETE"])
def api_delete_execution(live_id, exec_id):
    db.delete_live_trade_execution(exec_id)
    trade = db.get_live_trade(live_id)
    calc = logic.recalculate_live_trade(trade)
    # Re-open if was closed
    if trade["status"] == "closed" and not calc["is_closed"]:
        db.update_live_trade(live_id, status="open", closed_at=None, journal_trade_id=None)
    return jsonify({"ok": True, "calc": calc})


@app.route("/api/live/<int:live_id>/images", methods=["POST"])
def api_upload_live_image(live_id):
    if "image" not in request.files:
        return jsonify({"error": "No image file"}), 400
    f = request.files["image"]
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        return jsonify({"error": f"File type {ext} not allowed"}), 422
    unique_name = f"live_{live_id}_{uuid.uuid4().hex[:8]}{ext}"
    f.save(os.path.join(IMAGES_DIR, unique_name))
    caption = request.form.get("caption", "")
    image_id = db.add_live_trade_image(live_id, unique_name, caption)
    return jsonify({"ok": True, "id": image_id, "url": f"/images/{unique_name}", "caption": caption})


@app.route("/api/live/<int:live_id>/images", methods=["GET"])
def api_get_live_images(live_id):
    return jsonify(db.get_live_trade_images(live_id))


@app.route("/api/live/images/<int:image_id>", methods=["DELETE"])
def api_delete_live_image(image_id):
    filename = db.delete_live_trade_image(image_id)
    if filename:
        path = os.path.join(IMAGES_DIR, filename)
        if os.path.exists(path):
            os.remove(path)
    return jsonify({"ok": True})


@app.route("/api/live/<int:live_id>/recalc", methods=["GET"])
def api_live_recalc(live_id):
    trade = db.get_live_trade(live_id)
    if not trade:
        return jsonify({"error": "Trade not found"}), 404
    calc = logic.recalculate_live_trade(trade)
    return jsonify(calc)


# ── API: Day Notes & Images ──────────────────────────────────────────────────

@app.route("/api/day/<int:day_id>/notes", methods=["POST"])
def api_save_day_notes(day_id):
    body = request.get_json(silent=True) or {}
    db.update_day_notes(day_id, **body)
    return jsonify({"ok": True})


@app.route("/api/day/<int:day_id>/images", methods=["POST"])
def api_upload_day_image(day_id):
    if "image" not in request.files:
        return jsonify({"error": "No image file"}), 400
    f = request.files["image"]
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        return jsonify({"error": f"File type {ext} not allowed"}), 422
    unique_name = f"day_{day_id}_{uuid.uuid4().hex[:8]}{ext}"
    f.save(os.path.join(IMAGES_DIR, unique_name))
    caption = request.form.get("caption", "")
    image_id = db.add_day_image(day_id, unique_name, caption)
    return jsonify({"ok": True, "id": image_id, "url": f"/images/{unique_name}", "caption": caption})


@app.route("/api/day-image/<int:image_id>/caption", methods=["POST"])
def api_update_day_image_caption(image_id):
    body = request.get_json(silent=True) or {}
    db.update_day_image_caption(image_id, body.get("caption", ""))
    return jsonify({"ok": True})


@app.route("/api/day-image/<int:image_id>", methods=["DELETE"])
def api_delete_day_image(image_id):
    filename = db.delete_day_image(image_id)
    if filename:
        path = os.path.join(IMAGES_DIR, filename)
        if os.path.exists(path):
            os.remove(path)
    return jsonify({"ok": True})


# ── Market Internals ─────────────────────────────────────────────────────────

@app.route("/day/<int:day_id>/internals")
def internals_view(day_id):
    day = db.get_day_by_id(day_id)
    if not day:
        return render_template("404.html", message=f"Day #{day_id} not found"), 404
    return render_template("internals.html", day=day)


@app.route("/api/day/<int:day_id>/internals", methods=["GET"])
def api_get_internals(day_id):
    rows = db.get_internals_for_day(day_id)
    return jsonify(rows)


@app.route("/api/day/<int:day_id>/internals/<session>", methods=["POST"])
def api_upsert_internals(day_id, session):
    if session not in ("morning", "midday", "afternoon"):
        return jsonify({"error": "Invalid session"}), 400
    body = request.get_json(silent=True) or {}
    db.upsert_internals(day_id, session, **body)
    return jsonify({"ok": True})


# ── Setups ───────────────────────────────────────────────────────────────────

@app.route("/setups")
def setups_view():
    db.seed_setups()
    # Also seed from app_logic TAG_GROUPS fallback
    with db.get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM setups").fetchone()[0]
    if count == 0:
        setup_group = next((g for g in logic.TAG_GROUPS if g["id"] == "setup"), None)
        if setup_group:
            for tag in setup_group["tags"]:
                db.create_setup(tag)
    setups = db.get_all_setups()
    return render_template("setups.html", setups=setups)


@app.route("/setup/<int:setup_id>")
def setup_detail_view(setup_id):
    setup = db.get_setup(setup_id)
    if not setup:
        return render_template("404.html", message=f"Setup #{setup_id} not found"), 404
    # Date range from query
    date_from = request.args.get("from", "")
    date_to = request.args.get("to", "")
    preset = request.args.get("preset", "all")
    from datetime import timedelta
    today = date.today()
    if preset == "30d":
        date_from = (today - timedelta(days=30)).isoformat()
        date_to = today.isoformat()
    elif preset == "6mo":
        date_from = (today - timedelta(days=180)).isoformat()
        date_to = today.isoformat()
    elif preset == "1yr":
        date_from = (today - timedelta(days=365)).isoformat()
        date_to = today.isoformat()
    elif preset == "all":
        date_from = ""
        date_to = ""
    trades = db.get_setup_trades(setup["name"], date_from or None, date_to or None)
    # Compute stats
    total = len(trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    total_pnl = sum(t["pnl"] for t in trades)
    avg_pnl = round(total_pnl / total, 2) if total else 0
    win_rate = round(wins / total * 100, 1) if total else 0
    stats = {"total": total, "wins": wins, "total_pnl": round(total_pnl, 2), "avg_pnl": avg_pnl, "win_rate": win_rate}
    return render_template(
        "setup_detail.html", setup=setup, trades=trades, stats=stats,
        date_from=date_from, date_to=date_to, preset=preset,
    )


@app.route("/api/setup", methods=["POST"])
def api_create_setup():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    sid = db.create_setup(name)
    return jsonify({"ok": True, "id": sid})


@app.route("/api/setup/<int:setup_id>", methods=["PUT"])
def api_update_setup(setup_id):
    body = request.get_json(silent=True) or {}
    db.update_setup(setup_id, **body)
    return jsonify({"ok": True})


@app.route("/api/setup/<int:setup_id>", methods=["DELETE"])
def api_delete_setup(setup_id):
    db.delete_setup(setup_id)
    return jsonify({"ok": True})


@app.route("/api/setup/<int:setup_id>/images", methods=["POST"])
def api_upload_setup_image(setup_id):
    if "image" not in request.files:
        return jsonify({"error": "No image file"}), 400
    f = request.files["image"]
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        return jsonify({"error": f"File type {ext} not allowed"}), 422
    unique_name = f"setup_{setup_id}_{uuid.uuid4().hex[:8]}{ext}"
    f.save(os.path.join(IMAGES_DIR, unique_name))
    caption = request.form.get("caption", "")
    image_id = db.add_setup_image(setup_id, unique_name, caption)
    return jsonify({"ok": True, "id": image_id, "url": f"/images/{unique_name}", "caption": caption})


@app.route("/api/setup-image/<int:image_id>", methods=["DELETE"])
def api_delete_setup_image(image_id):
    filename = db.delete_setup_image(image_id)
    if filename:
        path = os.path.join(IMAGES_DIR, filename)
        if os.path.exists(path):
            os.remove(path)
    return jsonify({"ok": True})


# ── Observations ─────────────────────────────────────────────────────────────

@app.route("/observations")
def observations_view():
    date_from = request.args.get("from", "")
    date_to = request.args.get("to", "")
    preset = request.args.get("preset", "this_week")
    category = request.args.get("category", "all")
    group = request.args.get("group", "all")
    from datetime import timedelta
    today = date.today()
    if preset == "this_week":
        date_from = (today - timedelta(days=today.weekday())).isoformat()
        date_to = (today - timedelta(days=today.weekday()) + timedelta(days=6)).isoformat()
    elif preset == "last_week":
        start = today - timedelta(days=today.weekday() + 7)
        date_from = start.isoformat()
        date_to = (start + timedelta(days=6)).isoformat()
    elif preset == "2_weeks":
        date_from = (today - timedelta(days=14)).isoformat()
        date_to = today.isoformat()
    elif preset == "all":
        date_from = ""
        date_to = ""
    elif preset == "custom":
        date_from = request.args.get("from", "")
        date_to = request.args.get("to", "")
    obs = db.get_observations(
        date_from or None, date_to or None,
        category if category != "all" else None,
        obs_group=group if group != "all" else None,
    )
    return render_template(
        "observations.html",
        observations=obs,
        categories=logic.get_observation_categories(),
        groups=logic.get_observation_groups(),
        date_from=date_from, date_to=date_to, preset=preset,
        category=category, group=group,
    )


@app.route("/api/observation", methods=["POST"])
def api_create_observation():
    body = request.get_json(silent=True) or {}
    category = body.get("category", "general")
    # Accept both string and list — normalize to list for DB
    if isinstance(category, str):
        category = [category]
    obs_group = body.get("obs_group", [])
    # Accept both string and list
    if isinstance(obs_group, str):
        obs_group = [obs_group] if obs_group else []
    obs_id = db.create_observation(
        body.get("date", date.today().isoformat()),
        body.get("time", ""),
        body.get("text", ""),
        category,
        obs_group=obs_group,
    )
    return jsonify({"ok": True, "id": obs_id})


@app.route("/api/observation/<int:obs_id>", methods=["PUT"])
def api_update_observation(obs_id):
    body = request.get_json(silent=True) or {}
    db.update_observation(obs_id, **body)
    return jsonify({"ok": True})


@app.route("/api/observation/<int:obs_id>", methods=["DELETE"])
def api_delete_observation(obs_id):
    db.delete_observation(obs_id)
    return jsonify({"ok": True})


@app.route("/api/observation/<int:obs_id>/images", methods=["POST"])
def api_upload_observation_image(obs_id):
    if "image" not in request.files:
        return jsonify({"error": "No image file"}), 400
    f = request.files["image"]
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        return jsonify({"error": f"File type {ext} not allowed"}), 422
    unique_name = f"obs_{obs_id}_{uuid.uuid4().hex[:8]}{ext}"
    f.save(os.path.join(IMAGES_DIR, unique_name))
    caption = request.form.get("caption", "")
    image_id = db.add_observation_image(obs_id, unique_name, caption)
    return jsonify({"ok": True, "id": image_id, "url": f"/images/{unique_name}", "caption": caption})


@app.route("/api/obs-image/<int:image_id>", methods=["DELETE"])
def api_delete_obs_image(image_id):
    filename = db.delete_observation_image(image_id)
    if filename:
        path = os.path.join(IMAGES_DIR, filename)
        if os.path.exists(path):
            os.remove(path)
    return jsonify({"ok": True})


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    os.makedirs(IMAGES_DIR, exist_ok=True)
    port = int(os.environ.get("PORT", 5050))
    print("\n" + "=" * 45)
    print("  Trade Journal is running!")
    print("  Open this in your browser:")
    print(f"  --> http://127.0.0.1:{port}")
    print("=" * 45 + "\n")
    app.run(debug=False, host="127.0.0.1", port=port, use_reloader=False)
