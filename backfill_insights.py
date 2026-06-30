#!/usr/bin/env python3
"""
One-time (and safely re-runnable) backfill for the Weekly Review *trajectory* feature.

The weekly logging hook only records the week you're viewing. This script derives the
historical `insight_log` rows from your existing trades so the Trajectory zone has a
trailing window to work with. It is NOT run automatically — you run it explicitly,
check the rows, and can re-run it as often as you like.

Idempotent: each row is an upsert keyed on (account, week, detector), so re-running
overwrites the same rows rather than duplicating them.

Usage (Windows / macOS / Linux):
    python backfill_insights.py                # backfill every account, full history
    python backfill_insights.py --account 7    # just one account
    python backfill_insights.py --weeks 12     # only the most recent N weeks
"""

import sys
import argparse

import database as db
import app_logic as logic


def main():
    ap = argparse.ArgumentParser(description="Backfill insight_log from existing trades.")
    ap.add_argument("--account", type=int, default=None,
                    help="Account id to backfill (default: all accounts).")
    ap.add_argument("--weeks", type=int, default=None,
                    help="Limit to the most recent N trading weeks (default: full history).")
    args = ap.parse_args()

    # Ensure the schema exists even if the app has never been started on this machine.
    db.init_db()

    accounts = db.get_all_accounts()
    if args.account is not None:
        accounts = [a for a in accounts if a["id"] == args.account]
        if not accounts:
            print(f"No account with id {args.account}.")
            return 1

    if not accounts:
        print("No accounts found — nothing to backfill.")
        return 0

    print(f"Backfilling insight_log ({'last %d weeks' % args.weeks if args.weeks else 'full history'})…\n")
    grand_rows = 0
    for a in accounts:
        weeks = logic.backfill_insight_log(a["id"], max_weeks=args.weeks)
        rows = db.get_insight_window(a["id"], "0000", "9999")
        grand_rows += len(rows)
        fired = sum(1 for r in rows if r["fired"])
        qual = len({r["week_start"] for r in rows if r["qualifying"]})
        print(f"  • {a['name']:<18} (id {a['id']:>2}): {weeks:>3} weeks  →  "
              f"{len(rows):>4} rows  ({fired} fired, {qual} qualifying weeks)")

    print(f"\nDone. {grand_rows} insight_log rows total. "
          f"Safe to re-run — re-running overwrites the same rows (idempotent).")
    print("Open the Weekly Review page on your most recent week to see the Trajectory zone")
    print("(it needs ≥ 4 qualifying weeks of history before it appears).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
