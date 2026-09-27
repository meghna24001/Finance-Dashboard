import calendar
from datetime import date
from decimal import Decimal

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from finance import (
    budget_rows,
    month_transactions,
    monthly_trend,
    parse_month,
    shift_month,
    spending_by_category,
    today,
    totals,
)
from models import BankAccount

dashboard = Blueprint("dashboard", __name__)


@dashboard.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))
    return redirect(url_for("auth.login"))


@dashboard.route("/dashboard")
@login_required
def home():
    year, month = parse_month(request.args.get("month"))
    items = month_transactions(current_user.id, year, month)
    spending = spending_by_category(items)
    trend = monthly_trend(current_user.id, year, month)
    budgets = budget_rows(current_user.budgets, items)

    now = today()
    prev_year, prev_month = shift_month(year, month, -1)
    next_year, next_month = shift_month(year, month, 1)
    is_current_month = (year, month) == (now.year, now.month)

    month_summary = totals(items)
    income = month_summary["income"]
    spent = month_summary["spent"]
    balance = month_summary["balance"]

    savings_rate = None
    if income > 0:
        savings_rate = int(round(float((balance / income) * 100)))

    days_elapsed = now.day if is_current_month else calendar.monthrange(year, month)[1]
    daily_avg = (spent / Decimal(max(days_elapsed, 1))) if days_elapsed else Decimal("0")

    # Bank accounts
    accounts = BankAccount.query.filter_by(user_id=current_user.id, is_active=True).all()
    net_worth = sum((a.balance_hint for a in accounts if a.balance_hint is not None), Decimal("0"))

    # The numbers the charts draw. The exact, formatted amounts are printed on the page too.
    chart_data = {
        "currency": current_user.currency,
        "locale": f"en-{current_user.country}",
        "spending": {
            "labels": [row["name"] for row in spending],
            "values": [float(row["amount"]) for row in spending],
            "colors": [row["color"] for row in spending],
        },
        "trend": {
            "labels": [m["label"] for m in trend],
            "titles": [m["full_label"] for m in trend],
            "income": [float(m["income"]) for m in trend],
            "spent": [float(m["spent"]) for m in trend],
        },
    }

    return render_template(
        "dashboard.html",
        summary=month_summary,
        count=len(items),
        latest=items[:5],
        budget_top=budgets[:3],
        budget_total=len(budgets),
        spending=spending,
        trend=trend,
        trend_has_data=any(m["income"] or m["spent"] for m in trend),
        chart_data=chart_data,
        savings_rate=savings_rate,
        daily_avg=daily_avg,
        accounts=accounts,
        net_worth=net_worth,
        month_label=date(year, month, 1).strftime("%B %Y"),
        month_key=f"{year}-{month:02d}",
        prev_month=f"{prev_year}-{prev_month:02d}",
        next_month=None if is_current_month else f"{next_year}-{next_month:02d}",
    )
