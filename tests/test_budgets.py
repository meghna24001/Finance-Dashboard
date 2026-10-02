"""Simulates people setting monthly budgets and watching them fill up.
Uses a throwaway in-memory database, so your real data is never touched."""
import html as htmllib
import re
from datetime import date
from decimal import Decimal

from app import create_app
from config import TestConfig
from finance import shift_month, today
from tests.helpers import check, finish, flash_text, post, signup, text
from models import Budget, Category, Transaction, User, db

app = create_app(TestConfig)
NOW = today()


def month_day(back, day=10):
    y, m = shift_month(NOW.year, NOW.month, -back)
    return date(y, m, day)


def cat(email, name, kind="expense"):
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        c = Category.query.filter_by(user_id=user.id, name=name, type=kind).first()
        return c.id if c else None


def spend(email, category, amount, when=None, kind="expense"):
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        cid = Category.query.filter_by(user_id=user.id, name=category, type=kind).one().id
        db.session.add(Transaction(user_id=user.id, type=kind, amount=Decimal(str(amount)), category_id=cid, date=when or month_day(0)))
        db.session.commit()


def budgets_of(email):
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        return {b.category.name: str(b.amount) for b in Budget.query.filter_by(user_id=user.id)}


def budget_id(email, category):
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        return Budget.query.filter_by(
            user_id=user.id,
            category_id=cat(email, category),
            month=date(NOW.year, NOW.month, 1),
        ).one().id


def add_budget(client, email, category, amount, url="/budgets/new"):
    return post(client, url, {"category_id": cat(email, category), "amount": amount}, token_from="/budgets")


def errors_in(response):
    return [htmllib.unescape(m) for m in re.findall(r'<p class="field__error">(.*?)</p>', text(response))]


def cards(html):
    """Each budget on the page: (name, status label, 'spent of limit', 'left/over text')."""
    out = []
    for block in re.findall(r'<a class="budget".*?</a>', html, re.S):
        name = re.search(r'budget__name">(.*?)</span>', block).group(1)
        badge = re.search(r'<span class="badge[^"]*">\s*(.*?)\s*</span>', block, re.S).group(1)
        figures = re.search(r'budget__figures">\s*<span>(.*?)</span>\s*<span class="budget__left[^"]*">\s*(.*?)\s*</span>', block, re.S)
        amounts, percent = re.match(r"(.*) \((\d+)%\)$", figures.group(1)).groups()
        out.append((name, badge, amounts, figures.group(2), int(percent)))
    return out


asha = app.test_client(); signup(asha); A = "asha@example.com"
ben = app.test_client(); signup(ben, "Ben", "ben@example.com"); B = "ben@example.com"

# ---- access
anon = app.test_client()
for url in ["/budgets", "/budgets/1/edit"]:
    check(f"{url} needs login", anon.get(url).status_code == 302)
check("Adding a budget needs login", anon.post("/budgets/new", data={}).status_code in (302, 400))

# ---- empty state and the add form
page = text(asha.get("/budgets"))
check("With no budgets the page explains what they are", "No budgets yet" in page)
check("The add form offers expense categories only", ">Food<" in page and ">Salary<" not in page)
check("The monthly limit box is a number field labelled with the currency", "Monthly limit (USD)" in page and 'type="number"' in page)
check("The Budgets link is in the main navigation", 'href="/budgets"' in page)

# ---- creating
r = add_budget(asha, A, "Food", "500")
check("Adding a budget confirms it", flash_text(text(r)) == "Budget added.")
check("It is saved with the exact amount", budgets_of(A) == {"Food": "500.00"})
check("It starts at 0% with 'On track'", cards(text(r)) == [("Food", "On track", "$0.00 of $500.00", "$500.00 left", 0)])
check("Food is no longer offered in the add form", ">Food<" not in text(asha.get("/budgets")).split("Add a budget")[1])

# ---- mistakes
def try_budget(**overrides):
    data = {"category_id": cat(A, "Bills"), "amount": "100"}
    data.update(overrides)
    return post(asha, "/budgets/new", data, token_from="/budgets")

for bad, message in [("", "Enter an amount."), ("abc", "Enter an amount like 250 or 250.50."), ("0", "Enter an amount greater than zero."),
                     ("-5", "Enter an amount greater than zero."), ("1.234", "Use at most 2 decimal places."), ("100000000", "That amount is too large.")]:
    check(f"Limit {bad!r} -> {message!r}", errors_in(try_budget(amount=bad)) == [message])
check("A second budget for the same category is rejected", errors_in(try_budget(category_id=cat(A, "Food"))) == ["Choose a category."])
check("An income category can't get a budget", errors_in(try_budget(category_id=cat(A, "Salary", "income"))) == ["Choose a category."])
check("Someone else's category can't get a budget", errors_in(try_budget(category_id=cat(B, "Bills"))) == ["Choose a category."])
check("Missing category is rejected", errors_in(try_budget(category_id="")) == ["Choose a category."])
check("None of the rejected attempts saved anything", budgets_of(A) == {"Food": "500.00"})
check("Adding without the security code is rejected (400)", asha.post("/budgets/new", data={"category_id": cat(A, "Bills"), "amount": "5"}).status_code == 400)

# ---- how a budget fills up
def food_card():
    return [c for c in cards(text(asha.get("/budgets"))) if c[0] == "Food"][0]

spend(A, "Food", 200)
check("40% used is On track", food_card() == ("Food", "On track", "$200.00 of $500.00", "$300.00 left", 40))
spend(A, "Food", 199.99)
check("79.998% shows as 79% and is still On track", food_card()[1] == "On track" and food_card()[4] == 79)
spend(A, "Food", 0.01)
check("Exactly 80% is Close to limit", food_card()[1] == "Close to limit" and food_card()[4] == 80)
spend(A, "Food", 99.99)
check("99.998% shows as 99%, not 100%", food_card()[4] == 99 and food_card()[1] == "Close to limit")
spend(A, "Food", 0.01)
check("Spending exactly the limit says Limit reached with $0.00 left", food_card() == ("Food", "Limit reached", "$500.00 of $500.00", "$0.00 left", 100))
spend(A, "Food", 25.5)
check("One cent or more over the limit is Over budget", food_card() == ("Food", "Over budget", "$525.50 of $500.00", "$25.50 over", 105))
page = text(asha.get("/budgets"))
check("The bar is capped at 100% wide even when over, while the text shows 105%", 'style="width: 100%"' in page and "(105%)" in page)
check("Over-budget bars are marked", "meter--over" in page and "badge--over" in page)

# ---- only this month's spending counts, and only expenses
spend(A, "Food", 400, when=month_day(1))
spend(A, "Salary", 5000, kind="income")
check("Last month's spending doesn't count towards this month", food_card()[2] == "$525.50 of $500.00")
old = text(asha.get(f"/budgets?month={month_day(1).strftime('%Y-%m')}"))
check("Last month does not inherit this month's budget", not cards(old) and "No budgets yet" in old)
last_month_key = month_day(1).strftime("%Y-%m")
add_budget(asha, A, "Food", "250", url=f"/budgets/new?month={last_month_key}")
old = text(asha.get(f"/budgets?month={last_month_key}"))
check("A separate last-month limit is applied only to last month's spending", cards(old)[0][2] == "$400.00 of $250.00")
check("The current month's limit is unchanged", food_card()[2] == "$525.50 of $500.00")
check("Income never counts as spending", "5,000" not in text(asha.get("/budgets")))
check("A nonsense month falls back to this month", cards(text(asha.get("/budgets?month=banana")))[0][2] == "$525.50 of $500.00")

# ---- several budgets: order, totals, unbudgeted spending
add_budget(asha, A, "Transport", "100"); spend(A, "Transport", 10)
add_budget(asha, A, "Rent", "1000"); spend(A, "Rent", 900)
spend(A, "Shopping", 60)      # no budget for Shopping
page = text(asha.get("/budgets"))
check("Most-used budgets are listed first", [c[0] for c in cards(page)] == ["Food", "Rent", "Transport"])
check("Budgeted, spent and left are summed correctly", "$1,600.00" in page and "$1,435.50" in page and "$164.50" in page)
check("Spending without a budget is mentioned", "$60.00 was spent in categories that have no budget." in page)
check("Rent at 90% is Close to limit", cards(page)[1][1] == "Close to limit")

# ---- editing
bid = budget_id(A, "Transport")
edit = text(asha.get(f"/budgets/{bid}/edit"))
check("Edit page is filled in", 'value="100.00"' in edit and "Transport budget" in edit)
r = post(asha, f"/budgets/{bid}/edit", {"amount": "250.75"})
check("Saving a new limit works", flash_text(text(r)) == "Budget updated." and budgets_of(A)["Transport"] == "250.75")
r = post(asha, f"/budgets/{bid}/edit", {"amount": "oops"})
check("A bad limit shows an error and changes nothing", errors_in(r) == ["Enter an amount like 250 or 250.50."] and budgets_of(A)["Transport"] == "250.75")
check("Edits keep you on the month you were viewing", f"month={month_day(1).strftime('%Y-%m')}" in text(asha.get(f"/budgets/{bid}/edit?month={month_day(1).strftime('%Y-%m')}")))

# ---- privacy
check("Ben sees none of Asha's budgets", cards(text(ben.get("/budgets"))) == [] and "Food" in text(ben.get("/budgets")))
check("Ben can't open Asha's budget (404)", ben.get(f"/budgets/{bid}/edit").status_code == 404)
r = post(ben, f"/budgets/{bid}/edit", {"amount": "1"}, token_from="/budgets", follow=False)
check("Ben can't change Asha's budget (404)", r.status_code == 404 and budgets_of(A)["Transport"] == "250.75")
r = post(ben, f"/budgets/{bid}/delete", token_from="/budgets", follow=False)
check("Ben can't remove Asha's budget (404)", r.status_code == 404 and "Transport" in budgets_of(A))

# ---- removing
check("Remove by plain link (GET) is not allowed (405)", asha.get(f"/budgets/{bid}/delete").status_code == 405)
check("Remove without the security code is rejected (400)", asha.post(f"/budgets/{bid}/delete").status_code == 400)
r = post(asha, f"/budgets/{bid}/delete", token_from=f"/budgets/{bid}/edit")
check("Removing a budget works and says transactions are untouched", "untouched" in flash_text(text(r)) and "Transport" not in budgets_of(A))
with app.app_context():
    check("The Transport transactions are still there", Transaction.query.filter_by(category_id=cat(A, "Transport")).count() == 1)
check("Transport is offered again in the add form", ">Transport<" in text(asha.get("/budgets")).split("Add a budget")[1])

# ---- categories and budgets together
add_budget(asha, A, "Health", "50")
health = cat(A, "Health")
check("Category page warns that its budget will go too", "budget will be deleted with it" in text(asha.get(f"/categories/{health}/edit")))
r = post(asha, f"/categories/{health}/delete", token_from=f"/categories/{health}/edit")
check("Deleting an unused category also deletes its budget", cat(A, "Health") is None and "Health" not in budgets_of(A))
food = cat(A, "Food")
r = post(asha, f"/categories/{food}/delete", token_from=f"/categories/{food}/edit")
check("A category with transactions still can't be deleted, and keeps its budget", cat(A, "Food") == food and "Food" in budgets_of(A))

# ---- Home page
home = text(asha.get("/dashboard"))
check("Home shows a Budgets panel with the top budgets", "<h2 class=\"panel__title\">Budgets</h2>" in home and [c[0] for c in cards(home)] == ["Food", "Rent"])
add_budget(asha, A, "Bills", "80"); add_budget(asha, A, "Shopping", "300"); add_budget(asha, A, "Education", "20")
home = text(asha.get("/dashboard"))
check("Home shows at most 3 budgets, with a link to all", len(cards(home)) == 3 and "See all 5 budgets" in home)
newbie = app.test_client(); signup(newbie, "Nia", "nia@example.com")
check("A brand-new user doesn't see a Budgets panel yet", "Budgets</h2>" not in text(newbie.get("/dashboard")))
spend("nia@example.com", "Food", 5)
check("Once there's spending, Home invites them to set a budget", "Set a budget" in text(newbie.get("/dashboard")))
check("Ben's Home doesn't show Asha's budgets", "Rent" not in text(ben.get("/dashboard")).split("Budgets")[-1] if "Budgets</h2>" in text(ben.get("/dashboard")) else True)

finish()
