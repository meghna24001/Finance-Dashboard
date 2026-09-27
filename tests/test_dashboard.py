"""Checks the Home page: totals, the spending breakdown, the 6-month trend and the chart data.
Uses a throwaway in-memory database, so your real data is never touched."""
import json
import re
from datetime import date
from decimal import Decimal

from app import create_app
from config import TestConfig
from finance import shift_month, today
from tests.helpers import check, finish, signup, text
from models import Category, Transaction, User, db

app = create_app(TestConfig)
NOW = today()


def month_day(back, day=10):
    """A date `back` months before this month, e.g. back=0 is this month."""
    y, m = shift_month(NOW.year, NOW.month, -back)
    return date(y, m, day)


def add(email, kind, amount, category, when):
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        cat = Category.query.filter_by(user_id=user.id, name=category, type=kind).one()
        db.session.add(Transaction(user_id=user.id, type=kind, amount=Decimal(str(amount)), category_id=cat.id, date=when))
        db.session.commit()


def chart_data(client, url="/dashboard"):
    html = text(client.get(url))
    return json.loads(re.search(r'<script type="application/json" id="chart-data">(.*?)</script>', html, re.S).group(1))


def rows(html):
    """The category list under the doughnut: [(name, percent, amount), ...]"""
    return re.findall(r'breakdown__name">(.*?)</span>\s*<span class="breakdown__percent muted">(.*?)</span>\s*<span class="breakdown__amount">(.*?)</span>', html, re.S)


anon = app.test_client()
check("Home needs login", anon.get("/dashboard").status_code == 302)

# ---- brand-new user
newbie = app.test_client(); signup(newbie, "New", "new@example.com")
html = text(newbie.get("/dashboard"))
check("A new user sees the empty message and no charts", "Nothing recorded for" in html and "<canvas" not in html)
data = chart_data(newbie)
check("Chart data is still valid (empty) for a new user", data["spending"]["values"] == [] and data["trend"]["income"] == [0.0] * 6)

# ---- income only
inc = app.test_client(); signup(inc, "Ivy", "ivy@example.com")
add("ivy@example.com", "income", 1000, "Salary", month_day(0))
html = text(inc.get("/dashboard"))
check("With only income, the spending panel says there are no expenses", "No expenses in" in html and 'id="spending-chart"' not in html)
check("...but the 6-month chart is shown", 'id="trend-chart"' in html)

# ---- Asha: a realistic few months
asha = app.test_client(); signup(asha); A = "asha@example.com"
add(A, "expense", 60, "Food", month_day(0, 3))
add(A, "expense", 30, "Bills", month_day(0, 4))
add(A, "expense", 10, "Transport", month_day(0, 5))
add(A, "income", 2000, "Salary", month_day(0, 1))
add(A, "expense", "1234.56", "Rent", month_day(1))
add(A, "income", 900, "Freelance", month_day(1))
add(A, "expense", 40, "Food", month_day(3))
add(A, "expense", 999, "Food", month_day(7))       # older than the 6-month window
html = text(asha.get("/dashboard"))

check("Breakdown lists categories biggest first with percentages", rows(html) == [("Food", "60%", "$60.00"), ("Bills", "30%", "$30.00"), ("Transport", "10%", "$10.00")])
check("Summary shows this month's income, spent and left", "$2,000.00" in html and "$100.00" in html and "$1,900.00" in html)
data = chart_data(asha)
check("Doughnut data matches the list (labels, values, colours)", data["spending"]["labels"] == ["Food", "Bills", "Transport"] and data["spending"]["values"] == [60.0, 30.0, 10.0] and len(set(data["spending"]["colors"])) == 3)
check("List swatches use the same colours as the chart", all(c in html for c in data["spending"]["colors"]))
check("Currency and locale are passed to the chart", (data["currency"], data["locale"]) == ("USD", "en-US"))

labels = [month_day(b).strftime("%b") for b in range(5, -1, -1)]
check("Trend covers 6 months, oldest first, ending this month", data["trend"]["labels"] == labels and data["trend"]["titles"][-1] == NOW.strftime("%B %Y"))
check("Trend income per month is right", data["trend"]["income"] == [0.0, 0.0, 0.0, 0.0, 900.0, 2000.0])
check("Trend spending per month is right (old 999 is excluded)", data["trend"]["spent"] == [0.0, 0.0, 40.0, 0.0, 1234.56, 100.0])
check("The numbers table lists all 6 months with money formatting", html.count("<tbody>") == 1 and "$1,234.56" in html and html.count("<th scope=\"row\">") == 6)

# ---- more than 6 categories are lumped together
lump = app.test_client(); signup(lump, "Lump", "lump@example.com"); L = "lump@example.com"
for name, amount in [("Food", 80), ("Transport", 70), ("Rent", 60), ("Bills", 50), ("Shopping", 40), ("Health", 30), ("Entertainment", 20), ("Education", 10)]:
    add(L, "expense", amount, name, month_day(0))
got = rows(text(lump.get("/dashboard")))
check("Eight categories become six rows", len(got) == 6)
check("The five biggest stay separate", [g[0] for g in got[:5]] == ["Food", "Transport", "Rent", "Bills", "Shopping"])
check("The rest are lumped into 'Smaller categories' with the right total", got[5] == ("Smaller categories", "17%", "$60.00"))
check("The lump has its own grey colour", chart_data(lump)["spending"]["colors"][5] == "#9aa8a3")

# ---- tiny and exact amounts
tiny = app.test_client(); signup(tiny, "Tiny", "tiny@example.com"); T = "tiny@example.com"
add(T, "expense", 1000, "Food", month_day(0)); add(T, "expense", "0.10", "Bills", month_day(0))
check("A share below one percent says 'under 1%'", rows(text(tiny.get("/dashboard")))[1][1] == "under 1%")
exact = app.test_client(); signup(exact, "Exact", "exact@example.com"); X = "exact@example.com"
for _ in range(3):
    add(X, "expense", "0.10", "Food", month_day(0))
check("Three times $0.10 is exactly $0.30 (100%)", rows(text(exact.get("/dashboard"))) == [("Food", "100%", "$0.30")])

# ---- choosing a month
older = month_day(3)
page = text(asha.get(f"/dashboard?month={older.strftime('%Y-%m')}"))
check("An older month shows that month's spending", rows(page) == [("Food", "100%", "$40.00")])
check("The older month has a Next link; this month doesn't", "Next month" in page and "Next month" not in text(asha.get("/dashboard")))
d = chart_data(asha, f"/dashboard?month={older.strftime('%Y-%m')}")
check("The 6-month window moves to end at the chosen month", d["trend"]["titles"][-1] == older.strftime("%B %Y") and d["trend"]["spent"][-1] == 40.0)
check("Nonsense month falls back to this month", rows(text(asha.get("/dashboard?month=banana")))[0][0] == "Food" and "$60.00" in text(asha.get("/dashboard?month=banana")))

# ---- latest list
html = text(asha.get("/dashboard"))
check("Latest list shows this month's entries with dates", "Food, 03 " in html or "03 " in html)
check("Only 4 entries this month, so no 'See all' link", "See all" not in html)
for i in range(3):
    add(A, "expense", 5, "Food", month_day(0, 6 + i))
html = text(asha.get("/dashboard"))
check("With more than 5 entries, a 'See all 7 transactions' link appears", "See all 7 transactions" in html and f"/transactions?month={NOW.strftime('%Y-%m')}" in html)
check("Only the 5 latest are listed", html.count('class="txn"') == 5)

# ---- privacy
ben = app.test_client(); signup(ben, "Ben", "ben@example.com")
bh = text(ben.get("/dashboard")); bd = chart_data(ben)
check("Ben's charts are empty and contain none of Asha's numbers", bd["spending"]["values"] == [] and bd["trend"]["spent"] == [0.0] * 6 and "1,234.56" not in bh and "1234.56" not in bh)
jp = app.test_client(); signup(jp, "Jun", "jun@example.com", "JP")
check("A Japanese user gets yen and the Japanese locale", (chart_data(jp)["currency"], chart_data(jp)["locale"]) == ("JPY", "en-JP"))

# ---- files
html = text(asha.get("/dashboard"))
check("Home loads the local Chart.js and the dashboard script", "js/vendor/chart.umd.min.js" in html and "js/dashboard.js" in html)
check("The chart files are served by the app", all(asha.get(u).status_code == 200 for u in ["/static/js/vendor/chart.umd.min.js", "/static/js/dashboard.js", "/static/js/vendor/chart.js-LICENSE.md"]))
check("Other pages don't load the chart code", "chart.umd" not in text(asha.get("/profile")) and "chart-data" not in text(asha.get("/transactions")))
check("Charts have text alternatives", 'role="img"' in html and "Show the numbers" in html)

finish()
