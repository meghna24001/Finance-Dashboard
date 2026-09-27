"""Simulates people adding, editing and deleting income and expenses.
Uses a throwaway in-memory database, so your real data is never touched."""
import html as htmllib
import re
from datetime import timedelta

from app import create_app
from config import TestConfig
from finance import today
from tests.helpers import check, finish, flash_text, post, signup, text, token
from models import Category, Transaction, User, db

app = create_app(TestConfig)
NEW_EXPENSE, NEW_INCOME = "/transactions/new/expense", "/transactions/new/income"


def cat_id(email, name, kind="expense"):
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        return Category.query.filter_by(user_id=user.id, name=name, type=kind).one().id


def txns(email):
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        return [(t.type, str(t.amount), t.description, t.date.isoformat())
                for t in Transaction.query.filter_by(user_id=user.id).order_by(Transaction.id)]


def txn_id(email, description):
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        return Transaction.query.filter_by(user_id=user.id, description=description).one().id


def add_expense(client, email, amount, category="Food", when=None, note="", kind="expense"):
    url = NEW_EXPENSE if kind == "expense" else NEW_INCOME
    data = {"amount": amount, "category_id": cat_id(email, category, kind),
            "date": (when or today()).isoformat(), "description": note}
    return post(client, url, data)


def errors_in(response):
    return [htmllib.unescape(m) for m in re.findall(r'<p class="field__error">(.*?)</p>', text(response))]


asha = app.test_client()
signup(asha)
E = "asha@example.com"

# ---- new accounts start with categories
with app.app_context():
    u = User.query.filter_by(email=E).one()
    kinds = [c.type for c in u.categories]
    check("New account starts with 9 expense and 4 income categories", (kinds.count("expense"), kinds.count("income")) == (9, 4))

# ---- access control
anon = app.test_client()
for url in ["/transactions", NEW_EXPENSE, "/transactions/1/edit"]:
    check(f"{url} needs login", anon.get(url).status_code == 302)
check("Delete needs login", anon.post("/transactions/1/delete").status_code in (302, 400))
check("Unknown kind in the address is a 404", asha.get("/transactions/new/hack").status_code == 404)

# ---- the add forms
page = text(asha.get(NEW_EXPENSE))
check("Add-expense form offers expense categories only", ">Food<" in page and ">Salary<" not in page)
check("Add-income form offers income categories only", ">Salary<" in text(asha.get(NEW_INCOME)) and ">Food<" not in text(asha.get(NEW_INCOME)))
check("Amount box is a number field labelled with the currency", 'type="number"' in page and "Amount (USD)" in page)
check("Date box is a date picker starting on today", 'type="date"' in page and today().isoformat() in page)

# ---- adding
r = add_expense(asha, E, "250.50", "Food", note="Lunch")
html = text(r)
check("Adding an expense shows a confirmation", flash_text(html) == "Expense added.")
check("It appears in the list as a minus amount", "Lunch" in html and "−$250.50" in html)
r = add_expense(asha, E, "50000", "Salary", note="Monthly pay", kind="income")
html = text(r)
check("Adding income shows it as a plus amount", flash_text(html) == "Income added." and "+$50,000.00" in html)
check("Totals add up (income, spent, left)", "$50,000.00" in html and "$250.50" in html and "$49,749.50" in html)
check("Saved with exact amounts", txns(E) == [("expense", "250.50", "Lunch", today().isoformat()), ("income", "50000.00", "Monthly pay", today().isoformat())])

r = add_expense(asha, E, "10", "Transport", note="")
check("A note is optional (the category name is shown instead)", "Transport" in text(r))
r = add_expense(asha, E, "3", "Other", note="  Tea  ")
check("Notes are trimmed", txns(E)[-1][2] == "Tea")
r = add_expense(asha, E, "99999999.99", "Bills", note="Biggest allowed")
check("The largest allowed amount is accepted", txns(E)[-1][1] == "99999999.99")
tomorrow = today() + timedelta(days=1)
r = add_expense(asha, E, "1", "Food", when=tomorrow, note="Tomorrow ok")
check("Tomorrow's date is accepted (time zones differ)", len(txns(E)) == 6)
before = len(txns(E))

# ---- mistakes are rejected and nothing is saved
def try_add(**overrides):
    data = {"amount": "5", "category_id": cat_id(E, "Food"), "date": today().isoformat(), "description": "x"}
    data.update(overrides)
    return post(asha, NEW_EXPENSE, data)

for bad, message in [("", "Enter an amount."), ("abc", "Enter an amount like 250 or 250.50."), ("0", "Enter an amount greater than zero."),
                     ("-5", "Enter an amount greater than zero."), ("1.234", "Use at most 2 decimal places."),
                     ("NaN", "Enter an amount like 250 or 250.50."), ("Infinity", "Enter an amount like 250 or 250.50."),
                     ("100000000", "That amount is too large."), ("1e400", "That amount is too large."), ("1,500", "Enter an amount like 250 or 250.50.")]:
    r = try_add(amount=bad)
    check(f"Amount {bad!r} -> {message!r}", errors_in(r) == [message])

for bad, message in [("", "Choose a date."), ("31/12/2026", "Enter a valid date."), ("2099-01-01", "Choose a date that isn't in the future."),
                     ("1999-12-31", "Choose a date from the year 2000 onwards.")]:
    r = try_add(date=bad)
    check(f"Date {bad!r} -> {message!r}", errors_in(r) == [message])

check("Missing category is rejected", errors_in(try_add(category_id="")) == ["Choose a category."])
check("Non-numeric category is rejected", errors_in(try_add(category_id="abc")) == ["Choose a category."])
check("An income category can't be used for an expense", errors_in(try_add(category_id=cat_id(E, "Salary", "income"))) == ["Choose a category."])
check("Note over 200 characters is rejected", errors_in(try_add(description="x" * 201)) == ["Use 200 characters or fewer."])
check("A form with a mistake keeps what you typed", 'value="5"' in text(try_add(date="")) or 'value="5.00"' in text(try_add(date="")))
check("Nothing was saved by any of the rejected attempts", len(txns(E)) == before)
check("Form without the security code is rejected (400)", asha.post(NEW_EXPENSE, data={"amount": "5"}).status_code == 400)

# ---- exact decimal maths
carol = app.test_client()
signup(carol, "Carol", "carol@example.com", "US")
add_expense(carol, "carol@example.com", "0.10", "Food", note="a")
r = add_expense(carol, "carol@example.com", "0.20", "Food", note="b")
check("0.10 + 0.20 adds up to exactly $0.30", "$0.30" in text(r))

# ---- months
old_day = today() - timedelta(days=45)
add_expense(asha, E, "77", "Food", when=old_day, note="Old lunch")
month = old_day.strftime("%Y-%m")
current = text(asha.get("/transactions"))
check("Old transactions are not in the current month", "Old lunch" not in current)
check("The old month page shows it", "Old lunch" in text(asha.get(f"/transactions?month={month}")))
check("Current month has a Previous link and no Next link", "Previous month" in current and "Next month" not in current)
check("Older months have a Next link", "Next month" in text(asha.get(f"/transactions?month={month}")))
check("A nonsense month falls back to the current month", "Lunch" in text(asha.get("/transactions?month=garbage")))
check("Adding an old transaction takes you to its month", "Old lunch" in text(add_expense(asha, E, "1", "Food", when=old_day, note="Old two")))

# ---- newest day first
d1, d2 = today() - timedelta(days=2), today() - timedelta(days=1)
add_expense(asha, E, "2", "Food", when=d1, note="Two days ago")
add_expense(asha, E, "3", "Food", when=d2, note="Yesterday")
if d1.month == d2.month == today().month:
    html = text(asha.get("/transactions"))
    check("Days are listed newest first", html.index("Yesterday") < html.index("Two days ago"))

# ---- editing
tid = txn_id(E, "Lunch")
page = text(asha.get(f"/transactions/{tid}/edit"))
check("Edit page is filled in with the saved values", 'value="250.50"' in page and 'value="Lunch"' in page and today().isoformat() in page)
check("Edit page says Edit expense", "Edit expense" in page)
r = post(asha, f"/transactions/{tid}/edit", {"amount": "300", "category_id": cat_id(E, "Bills"), "date": today().isoformat(), "description": "Lunch out"})
check("Saving an edit updates the entry", ("expense", "300.00", "Lunch out", today().isoformat()) in txns(E) and flash_text(text(r)) == "Changes saved.")
r = post(asha, f"/transactions/{tid}/edit", {"amount": "oops", "category_id": cat_id(E, "Bills"), "date": today().isoformat(), "description": "Lunch out"})
check("A bad edit shows an error and changes nothing", errors_in(r) == ["Enter an amount like 250 or 250.50."] and ("expense", "300.00", "Lunch out", today().isoformat()) in txns(E))
r = post(asha, f"/transactions/{tid}/edit", {"amount": "300", "category_id": cat_id(E, "Bills"), "date": today().isoformat(), "description": "Lunch out", "type": "income"})
check("The type (expense/income) can't be changed by editing", ("expense", "300.00", "Lunch out", today().isoformat()) in txns(E))

# ---- two people stay separate
ben = app.test_client()
signup(ben, "Ben Ito", "ben@example.com", "US")
B = "ben@example.com"
check("Ben sees none of Asha's transactions", "Lunch out" not in text(ben.get("/transactions")) and "Monthly pay" not in text(ben.get("/transactions")))
check("Ben's totals are zero", text(ben.get("/dashboard")).count("$0.00") == 3)
check("Ben can't open Asha's transaction (404)", ben.get(f"/transactions/{tid}/edit").status_code == 404)
r = post(ben, f"/transactions/{tid}/edit", {"amount": "1", "category_id": cat_id(B, "Food"), "date": today().isoformat(), "description": "hacked"}, token_from=NEW_EXPENSE, follow=False)
check("Ben can't change Asha's transaction (404)", r.status_code == 404 and ("expense", "300.00", "Lunch out", today().isoformat()) in txns(E))
r = post(ben, f"/transactions/{tid}/delete", token_from=NEW_EXPENSE, follow=False)
check("Ben can't delete Asha's transaction (404)", r.status_code == 404 and any(t[2] == "Lunch out" for t in txns(E)))
r = post(ben, NEW_EXPENSE, {"amount": "5", "category_id": cat_id(E, "Food"), "date": today().isoformat(), "description": "borrowed category"}, token_from=NEW_EXPENSE)
check("Ben can't use Asha's category in his transaction", errors_in(r) == ["Choose a category."] and txns(B) == [])

# ---- dashboard
html = text(asha.get("/dashboard"))
check("Dashboard shows this month's totals for Asha", "$50,000.00" in html and "Add expense" in html and "Add income" in html)
newbie = app.test_client(); signup(newbie, "New", "new@example.com", "US")
check("A brand-new user sees the empty message", "Nothing recorded for" in text(newbie.get("/dashboard")))

# ---- deleting
check("Delete by plain link (GET) is not allowed (405)", asha.get(f"/transactions/{tid}/delete").status_code == 405)
check("Delete without the security code is rejected (400)", asha.post(f"/transactions/{tid}/delete").status_code == 400)
r = post(asha, f"/transactions/{tid}/delete", token_from=f"/transactions/{tid}/edit")
check("Deleting removes it and confirms", flash_text(text(r)) == "Transaction deleted." and not any(t[2] in ("Lunch", "Lunch out") for t in txns(E)))
check("Deleted transaction is gone from the totals page", "Lunch out" not in text(r))
check("Edit page for a deleted transaction is a 404", asha.get(f"/transactions/{tid}/edit").status_code == 404)

finish()
