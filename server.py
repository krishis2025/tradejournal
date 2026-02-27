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


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    today        = date.today()
    default_from = (today - timedelta(days=30)).isoformat()
    default_to   = today.isoformat()

    date_from = request.args.get("from",   default_from)
    date_to   = request.args.get("to",     default_to)
    preset    = request.args.get("preset", "30d")

    # Portfolio comes from query string (set by nav JS via page reload)
    portfolio_id = request.args.get("portfolio") or None

    days = db.get_all_days(date_from, date_to, portfolio_id)

    return render_template(
        "index.html",
        days=days,
        date_from=date_from,
        date_to=date_to,
        portfolio_id=portfolio_id,
        preset=preset,
        today=today.isoformat(),
    )


@app.route("/day/<int:day_id>")
def day_view(day_id):
    day = db.get_day_by_id(day_id)
    if not day:
        return render_template("404.html", message=f"Day #{day_id} not found"), 404
    trades = db.get_trades_for_day(day_id)
    return render_template(
        "day.html",
        day=day,
        trades=trades,
        tag_groups=logic.get_tag_groups(),
        tags_json=json.dumps(logic.get_tag_groups())
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
    return render_template(
        "trade.html",
        trade=trade,
        tag_groups=logic.get_tag_groups(),
        tags_json=json.dumps(logic.get_tag_groups())
    )


@app.route("/analytics")
def analytics():
    portfolio_id = request.args.get("portfolio") or None
    data         = db.get_analytics(portfolio_id)
    portfolios   = db.get_all_portfolios()
    return render_template(
        "analytics.html",
        data=data,
        data_json=json.dumps(data),
        portfolios=portfolios,
        portfolio_id=portfolio_id,
    )


@app.route("/portfolios")
def portfolios_view():
    return render_template("portfolios.html", portfolios=db.get_all_portfolios())


@app.route("/settings")
def settings_view():
    tag_groups = logic.get_tag_groups()
    defaults   = logic.TAG_GROUPS
    trade_defaults = logic.get_trade_defaults()
    instrument_config = logic.get_instrument_config()
    return render_template(
        "settings.html",
        tag_groups=tag_groups,
        defaults=defaults,
        defaults_json=json.dumps(defaults),
        tag_groups_json=json.dumps(tag_groups),
        trade_defaults=trade_defaults,
        instrument_config=instrument_config,
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

    open_trades  = db.get_all_live_trades(status="open", date_from=date_from, date_to=date_to)
    closed_trades = db.get_all_live_trades(status="closed", date_from=date_from, date_to=date_to)

    # Pre-compute calc for each open trade
    for t in open_trades:
        full = db.get_live_trade(t["id"])
        t["levels"] = full.get("levels", [])
        t["executions"] = full.get("executions", [])
        t["calc"] = logic.recalculate_live_trade(full)

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
    portfolio_id = request.args.get("portfolio") or None
    return render_template(
        "live_entry_legacy.html",
        trade=None,
        tag_groups=logic.get_tag_groups(),
        tags_json=json.dumps(logic.get_tag_groups()),
        trade_defaults=logic.get_trade_defaults(),
        instrument_config_json=json.dumps(logic.get_instrument_config()),
        portfolio_id=portfolio_id,
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
        portfolio_id=trade.get("portfolio_id"),
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
    portfolio_id = request.form.get("portfolio_id") or None
    if portfolio_id:
        portfolio_id = int(portfolio_id)
    try:
        result = logic.import_file(f.filename, f.read(), portfolio_id)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500


# ── API: Trading Days ─────────────────────────────────────────────────────────

@app.route("/api/day/<int:day_id>", methods=["DELETE"])
def api_delete_day(day_id):
    day = db.get_day_by_id(day_id)
    if not day:
        return jsonify({"error": "Day not found"}), 404
    db.delete_day(day_id)
    return jsonify({"ok": True, "deleted": day_id})


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
    db.update_trade_notes(trade_id, notes)
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


# ── API: Portfolios ───────────────────────────────────────────────────────────

@app.route("/api/portfolio", methods=["POST"])
def api_create_portfolio():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Portfolio name is required"}), 400
    try:
        pid = db.create_portfolio(name, body.get("description", ""), body.get("color", "#4fffb0"))
        return jsonify({"ok": True, "id": pid})
    except Exception as e:
        return jsonify({"error": str(e)}), 422


@app.route("/api/portfolio/<int:portfolio_id>", methods=["PUT"])
def api_update_portfolio(portfolio_id):
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Portfolio name is required"}), 400
    db.update_portfolio(portfolio_id, name, body.get("description", ""), body.get("color", "#4fffb0"))
    return jsonify({"ok": True})


@app.route("/api/portfolio/<int:portfolio_id>", methods=["DELETE"])
def api_delete_portfolio(portfolio_id):
    db.delete_portfolio(portfolio_id)
    return jsonify({"ok": True})


@app.route("/api/portfolios")
def api_portfolios():
    return jsonify(db.get_all_portfolios())


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
    portfolio_id = request.args.get("portfolio") or None
    return jsonify(db.get_analytics(portfolio_id))


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
            portfolio_id=body.get("portfolio_id"),
            direction=body["direction"],
            instrument=body["instrument"],
            entry_price=float(body["entry_price"]),
            entry_time=body["entry_time"],
            total_qty=int(body["total_qty"]),
            mode=body["mode"],
            notes=body.get("notes", ""),
            tags_json=json.dumps(body.get("tags", {})),
        )
        # Compute and save default levels
        levels = logic.compute_live_trade_plan(
            body["direction"], body["instrument"],
            float(body["entry_price"]), int(body["total_qty"]), body["mode"]
        )
        db.set_live_trade_levels(live_id, levels)
        return jsonify({"ok": True, "id": live_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/live/<int:live_id>", methods=["PUT"])
def api_update_live_trade(live_id):
    body = request.get_json(silent=True) or {}
    allowed = {"notes", "tags_json", "status"}
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


@app.route("/api/live/<int:live_id>/recalc", methods=["GET"])
def api_live_recalc(live_id):
    trade = db.get_live_trade(live_id)
    if not trade:
        return jsonify({"error": "Trade not found"}), 404
    calc = logic.recalculate_live_trade(trade)
    return jsonify(calc)


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    os.makedirs(IMAGES_DIR, exist_ok=True)
    print("\n" + "=" * 45)
    print("  Trade Journal is running!")
    print("  Open this in your browser:")
    print("  --> http://127.0.0.1:5000")
    print("=" * 45 + "\n")
    app.run(debug=False, host="127.0.0.1", port=5000, use_reloader=False)
