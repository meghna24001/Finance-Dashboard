"""
FinSight — Smart notification computation.
All alerts are computed on-demand from existing data; no extra DB table.
"""
from datetime import datetime, timezone, date as date_type
from decimal import Decimal
import hashlib

from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from finance import budget_rows, month_transactions, parse_month, today
from models import Transaction

notifications_bp = Blueprint("notifications", __name__)




def compute_notifications(user):
    """Return a list of notification dicts for the given user."""
    now = today()
    items_this_month = month_transactions(user.id, now.year, now.month)
    budgets = budget_rows(user.budgets, items_this_month)

    notifs = []
    def add(icon, message, kind="info"):
        stable_id = hashlib.sha256(f"{user.id}|{kind}|{message}".encode()).hexdigest()[:24]
        notifs.append({
            "id": stable_id,
            "icon": icon,
            "message": message,
            "kind": kind,
            "created_at": datetime.combine(now, datetime.min.time(), tzinfo=timezone.utc).isoformat(),
        })

    # 1. Budget exceeded
    for row in budgets:
        if row["status"] == "over":
            over_by = row["over_by"]
            add("🔴", f"{row['name']} budget exceeded by {over_by:.0f}", "danger")

    # 2. Budget warning (≥80%)
    for row in budgets:
        if row["status"] == "close":
            add("⚠️", f"{row['name']} budget is {row['percent']}% used", "warning")

    # 3. Month-end reminder (last 3 days)
    import calendar
    last_day = calendar.monthrange(now.year, now.month)[1]
    days_left = last_day - now.day
    if 0 <= days_left <= 3 and items_this_month:
        add("📅", f"Only {days_left} day{'s' if days_left != 1 else ''} left this month — review your spending", "info")

    # 4. No transactions logged today
    today_txns = [t for t in items_this_month if t.date == now]
    if not today_txns and items_this_month:
        add("📝", "No transactions logged today — keep your record up to date", "info")

    # 5. Welcome (brand-new user)
    total_count = Transaction.query.filter_by(user_id=user.id).count()
    if total_count == 0:
        add("👋", "Welcome to FinSight! Add your first transaction to get started", "info")

    # 6. Logging streak (transactions logged every day for 3+ days)
    dates = sorted(set(t.date for t in items_this_month), reverse=True)
    streak = 0
    check = now
    for d in dates:
        if d == check:
            streak += 1
            from datetime import timedelta
            check = check - timedelta(days=1)
        else:
            break
    if streak >= 3:
        add("🔥", f"You've logged transactions {streak} days in a row — keep it up!", "success")

    # 7. Savings rate check
    from finance import totals
    summary = totals(items_this_month)
    if summary["income"] > 0:
        rate = (summary["balance"] / summary["income"] * 100).quantize(Decimal("1"))
        if rate < 0:
            add("📉", f"You've spent more than you earned this month ({rate}% savings rate)", "danger")
        elif rate < 20:
            add("💡", f"Your savings rate is {rate}% this month — try to aim for 20%+", "warning")

    return notifs


@notifications_bp.route("/api/notifications")
@login_required
def get_notifications():
    notifs = compute_notifications(current_user)
    return jsonify({"notifications": notifs})
