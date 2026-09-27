"""Simulates people managing their own categories.
Uses a throwaway in-memory database, so your real data is never touched."""
import html as htmllib
import re

from app import create_app
from config import TestConfig
from finance import today
from tests.helpers import check, finish, flash_text, post, signup, text
from models import Category, Transaction, User, db

app = create_app(TestConfig)


def cat(email, name, kind="expense"):
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        c = Category.query.filter_by(user_id=user.id, name=name, type=kind).first()
        return c.id if c else None


def names(email, kind):
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        return sorted(c.name for c in Category.query.filter_by(user_id=user.id, type=kind))


def errors_in(response):
    return [htmllib.unescape(m) for m in re.findall(r'<p class="field__error">(.*?)</p>', text(response))]


def add_category(client, name, kind="expense"):
    return post(client, "/categories/new", {"name": name, "kind": kind}, token_from="/categories")


asha = app.test_client(); signup(asha); A = "asha@example.com"
ben = app.test_client(); signup(ben, "Ben", "ben@example.com"); B = "ben@example.com"

# ---- access + listing
check("Categories page needs login", app.test_client().get("/categories").status_code == 302)
page = text(asha.get("/categories"))
check("Page lists the starter categories in two groups", "Expense categories" in page and "Income categories" in page and ">Food<" in page and ">Salary<" in page)
check("Each category shows how many transactions use it", "0 transactions" in page)

# ---- adding
r = add_category(asha, "Snacks")
check("Adding a category confirms and lists it", flash_text(text(r)) == "Category added." and ">Snacks<" in text(r))
check("It is saved as an expense category", "Snacks" in names(A, "expense") and "Snacks" not in names(A, "income"))
check("Duplicate name is rejected, ignoring capital letters", errors_in(add_category(asha, "snacks")) == ["You already have a category with this name."])
check("The same name is allowed as an income category", flash_text(text(add_category(asha, "Snacks", "income"))) == "Category added.")
check("'Other' already exists in both kinds, so it can't be added again", errors_in(add_category(asha, "other")) == ["You already have a category with this name."])
check("Blank name is rejected", errors_in(add_category(asha, "   ")) == ["Enter a category name."])
check("Name over 40 characters is rejected", errors_in(add_category(asha, "x" * 41)) == ["Use 40 characters or fewer."])
add_category(asha, "  Eating    out ")
check("Extra spaces are tidied up", "Eating out" in names(A, "expense"))
check("Made-up type is rejected", "Not a valid choice" in text(post(asha, "/categories/new", {"name": "Zed", "kind": "hack"}, token_from="/categories")) and cat(A, "Zed") is None)
check("Adding without the security code is rejected (400)", asha.post("/categories/new", data={"name": "Nope", "kind": "expense"}).status_code == 400)
check("Ben doesn't see Asha's custom categories", "Snacks" not in text(ben.get("/categories")))
check("Asha's new category appears in her add-expense form", ">Snacks<" in text(asha.get("/transactions/new/expense")))
check("...but not in Ben's", ">Snacks<" not in text(ben.get("/transactions/new/expense")))

# ---- renaming
snacks = cat(A, "Snacks")
page = text(asha.get(f"/categories/{snacks}/edit"))
check("Edit page shows the current name", 'value="Snacks"' in page and "Edit expense category" in page)
r = post(asha, f"/categories/{snacks}/edit", {"name": "Treats"})
check("Renaming works", flash_text(text(r)) == "Category renamed." and "Treats" in names(A, "expense") and "Snacks" not in names(A, "expense"))
check("Renaming to an existing name is rejected", errors_in(post(asha, f"/categories/{snacks}/edit", {"name": "food"})) == ["You already have a category with this name."])
check("'Renaming' to its own name (different capitals) is fine", flash_text(text(post(asha, f"/categories/{snacks}/edit", {"name": "TREATS"}))) == "Category renamed.")
check("Blank rename is rejected", errors_in(post(asha, f"/categories/{snacks}/edit", {"name": ""})) == ["Enter a category name."])

# ---- categories in use can't be deleted
post(asha, "/transactions/new/expense", {"amount": "12", "category_id": cat(A, "Food"), "date": today().isoformat(), "description": "Lunch"})
page = text(asha.get("/categories"))
check("Count updates and uses the singular for one", "1 transaction<" in page)
food = cat(A, "Food")
check("Edit page explains why a used category can't be deleted", "so it can't be deleted" in text(asha.get(f"/categories/{food}/edit")) and "Delete category" not in text(asha.get(f"/categories/{food}/edit")))
r = post(asha, f"/categories/{food}/delete", token_from=f"/categories/{food}/edit")
check("Deleting a used category is blocked with a clear message", "used by 1 transaction, so it can't be deleted" in flash_text(text(r)) and cat(A, "Food") == food)

# ---- unused categories can be deleted
treats = snacks  # renamed earlier; the name is now "TREATS"
check("Delete by plain link (GET) is not allowed (405)", asha.get(f"/categories/{treats}/delete").status_code == 405)
check("Delete without the security code is rejected (400)", asha.post(f"/categories/{treats}/delete").status_code == 400)
r = post(asha, f"/categories/{treats}/delete", token_from=f"/categories/{treats}/edit")
check("Deleting an unused category works", flash_text(text(r)) == "Category deleted." and cat(A, "TREATS") is None)

# ---- categories are private
bfood = cat(B, "Food")
check("Ben can't open Asha's category (404)", ben.get(f"/categories/{food}/edit").status_code == 404)
r = post(ben, f"/categories/{food}/edit", {"name": "Hacked"}, token_from="/categories", follow=False)
check("Ben can't rename Asha's category (404)", r.status_code == 404 and cat(A, "Food") == food)
r = post(ben, f"/categories/{cat(A, 'Bills')}/delete", token_from="/categories", follow=False)
check("Ben can't delete Asha's category (404)", r.status_code == 404 and cat(A, "Bills") is not None)
check("Ben's own Food category is untouched", cat(B, "Food") == bfood)

# ---- nothing left to choose from
for name in list(names(A, "income")):
    cid = cat(A, name, "income")
    post(asha, f"/categories/{cid}/delete", token_from=f"/categories/{cid}/edit")
check("All unused income categories can be removed", names(A, "income") == [])
r = asha.get("/transactions/new/income", follow_redirects=True)
check("With no income categories, adding income sends you to add one first", flash_text(text(r)) == "Add an income category first." and "Add a category" in text(r))

finish()
