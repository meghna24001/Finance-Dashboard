"""Small helpers for working with months and money totals."""
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from sqlalchemy.orm import joinedload

from extensions import db
from models import Transaction

# Colours for the "where your money went" chart. Each one is also written out as a
# name and a percentage next to the chart, so nobody has to rely on colour alone.
CHART_COLORS = ["#2563eb", "#f97316", "#14b8a6", "#8b5cf6", "#ec4899", "#84cc16"]
LUMPED_COLOR = "#9aa8a3"
MAX_SLICES = 6


def today():
    """Today's date on the server (UTC)."""
    return datetime.now(timezone.utc).date()


def parse_month(text):
    """Turn "2026-09" into (2026, 9). Anything unusable gives the current month."""
    now = today()
    try:
        year_text, month_text = (text or "").split("-")
        year, month = int(year_text), int(month_text)
        if 2000 <= year <= now.year + 1 and 1 <= month <= 12:
            return year, month
    except ValueError:
        pass
    return now.year, now.month


def shift_month(year, month, change):
    """Move forward or back by whole months: (2026, 1), -1 -> (2025, 12)."""
    index = year * 12 + (month - 1) + change
    return index // 12, index % 12 + 1


def month_transactions(user_id, year, month):
    """All of one person's transactions in one month, newest first."""
    first = date(year, month, 1)
    next_year, next_month = shift_month(year, month, 1)
    return (
        Transaction.query.filter(
            Transaction.user_id == user_id,
            Transaction.date >= first,
            Transaction.date < date(next_year, next_month, 1),
        )
        .options(joinedload(Transaction.category))  # fetch category names in the same query
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .all()
    )


def totals(transactions):
    """Income, spending and what's left. Adds exact decimals, so 0.10 + 0.20 is 0.30."""
    income = sum((t.amount for t in transactions if t.type == "income"), Decimal("0"))
    spent = sum((t.amount for t in transactions if t.type == "expense"), Decimal("0"))
    return {"income": income, "spent": spent, "balance": income - spent}


def spending_by_category(transactions):
    """Expenses grouped by category, biggest first, ready for the chart and its list.

    With more than 6 categories, the smallest ones are lumped into "Smaller categories"
    so the chart stays readable."""
    by_name = defaultdict(Decimal)
    for t in transactions:
        if t.type == "expense":
            by_name[t.category.name if t.category else "Uncategorized"] += t.amount

    ranked = sorted(by_name.items(), key=lambda pair: (-pair[1], pair[0].casefold()))
    lumped = len(ranked) > MAX_SLICES
    if lumped:
        rest = sum((amount for _, amount in ranked[MAX_SLICES - 1:]), Decimal("0"))
        ranked = ranked[: MAX_SLICES - 1] + [("Smaller categories", rest)]

    total = sum((amount for _, amount in ranked), Decimal("0"))
    rows = []
    for index, (name, amount) in enumerate(ranked):
        percent = (amount / total * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        is_lump = lumped and index == len(ranked) - 1
        rows.append(
            {
                "name": name,
                "amount": amount,
                "percent_text": "under 1%" if percent < 1 else f"{percent}%",
                "color": LUMPED_COLOR if is_lump else CHART_COLORS[index],
            }
        )
    return rows


def monthly_trend(user_id, year, month, months=6):
    """Income and spending for each of the last few months, oldest first."""
    start_year, start_month = shift_month(year, month, -(months - 1))
    end_year, end_month = shift_month(year, month, 1)
    found = (
        db.session.query(Transaction.date, Transaction.type, Transaction.amount)
        .filter(
            Transaction.user_id == user_id,
            Transaction.date >= date(start_year, start_month, 1),
            Transaction.date < date(end_year, end_month, 1),
        )
        .all()
    )

    income, spent = defaultdict(Decimal), defaultdict(Decimal)
    for day, kind, amount in found:
        if kind == "income":
            income[(day.year, day.month)] += amount
        elif kind == "expense":
            spent[(day.year, day.month)] += amount

    result = []
    for back in range(months - 1, -1, -1):
        y, m = shift_month(year, month, -back)
        first = date(y, m, 1)
        result.append(
            {
                "label": first.strftime("%b"),
                "full_label": first.strftime("%B %Y"),
                "income": income[(y, m)],
                "spent": spent[(y, m)],
            }
        )
    return result


def date_range_trend(user_id, start_date, end_date):
    """Income and spending by month within an inclusive date range."""
    start_month = date(start_date.year, start_date.month, 1)
    end_month = date(end_date.year, end_date.month, 1)
    month_count = (end_month.year - start_month.year) * 12 + end_month.month - start_month.month + 1

    found = (
        db.session.query(Transaction.date, Transaction.type, Transaction.amount)
        .filter(
            Transaction.user_id == user_id,
            Transaction.date >= start_date,
            Transaction.date <= end_date,
        )
        .all()
    )

    income, spent = defaultdict(Decimal), defaultdict(Decimal)
    for day, kind, amount in found:
        if kind == "income":
            income[(day.year, day.month)] += amount
        elif kind == "expense":
            spent[(day.year, day.month)] += amount

    result = []
    for offset in range(month_count):
        year, month = shift_month(start_month.year, start_month.month, offset)
        first = date(year, month, 1)
        result.append(
            {
                "label": first.strftime("%b %Y"),
                "full_label": first.strftime("%B %Y"),
                "income": income[(year, month)],
                "spent": spent[(year, month)],
            }
        )
    return result


CLOSE_TO_LIMIT = Decimal("80")  # "close" starts at 80% of the limit


def budget_rows(budgets, transactions):
    """For one month: each budget with how much is spent, what is left and how it looks.
    Most-used budgets come first, so the ones that need attention are at the top."""
    spent_by_category = defaultdict(Decimal)
    for t in transactions:
        if t.type == "expense":
            spent_by_category[t.category_id] += t.amount

    rows = []
    for budget in budgets:
        spent = spent_by_category[budget.category_id]
        ratio = spent / budget.amount * 100
        percent = int(ratio.to_integral_value(rounding=ROUND_FLOOR))  # 99.6% shows as 99%, never 100%
        if spent > budget.amount:
            status = "over"
        elif ratio >= CLOSE_TO_LIMIT:
            status = "close"
        else:
            status = "ok"
        rows.append(
            {
                "budget": budget,
                "name": budget.category.name,
                "limit": budget.amount,
                "spent": spent,
                "left": budget.amount - spent,
                "over_by": spent - budget.amount,
                "percent": percent,
                "bar": min(percent, 100),
                "status": status,
                "ratio": ratio,
            }
        )
    rows.sort(key=lambda r: (-r["ratio"], r["name"].casefold()))
    return rows


def budget_summary(rows, transactions, budgets):
    """Totals across all budgets, plus spending in categories that have no budget."""
    budgeted_ids = {b.category_id for b in budgets}
    limit = sum((r["limit"] for r in rows), Decimal("0"))
    spent = sum((r["spent"] for r in rows), Decimal("0"))
    unbudgeted = sum(
        (t.amount for t in transactions if t.type == "expense" and t.category_id not in budgeted_ids),
        Decimal("0"),
    )
    return {
        "limit": limit,
        "spent": spent,
        "left": limit - spent,
        "unbudgeted": unbudgeted,
        "over": sum(1 for r in rows if r["status"] == "over"),
        "close": sum(1 for r in rows if r["status"] == "close"),
    }
