"""Checks the small JSON endpoints that the offline queue uses to send waiting transactions.
Uses a throwaway in-memory database, so your real data is never touched."""
import uuid
from datetime import timedelta

from app import create_app
from config import TestConfig
from finance import today
from tests.helpers import check, finish, signup
from models import Category, SyncReceipt, Transaction, User, db

app = create_app(TestConfig)


def cat(email, name, kind="expense"):
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        return Category.query.filter_by(user_id=user.id, name=name, type=kind).one().id


def rows(email):
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        return [(t.type, str(t.amount), t.description, t.date.isoformat()) for t in Transaction.query.filter_by(user_id=user.id).order_by(Transaction.id)]


def send(client, payload, token=None, headers=None):
    hdrs = {"X-CSRFToken": token} if token else {}
    hdrs.update(headers or {})
    return client.post("/api/transactions", json=payload, headers=hdrs)


def entry(email, **overrides):
    data = {"client_id": str(uuid.uuid4()), "kind": "expense", "amount": "12.50", "category_id": cat(email, "Food"),
            "date": today().isoformat(), "description": "Queued lunch"}
    data.update(overrides)
    return data


anon = app.test_client()
check("/api/ping works without signing in", anon.get("/api/ping").status_code == 200 and anon.get("/api/ping").get_json() == {"ok": True})
check("/api/ping is never cached", anon.get("/api/ping").headers["Cache-Control"] == "no-store")
r = anon.get("/api/session")
check("/api/session says 401 (not a redirect) when signed out", r.status_code == 401 and r.get_json()["error"])
check("Sending a transaction while signed out is refused (401 or 400)", send(anon, {"kind": "expense"}).status_code in (400, 401))

asha = app.test_client(); signup(asha); A = "asha@example.com"
session = asha.get("/api/session").get_json()
with app.app_context():
    uid = User.query.filter_by(email=A).one().id
check("/api/session gives the user's ID and a security code", session["user_id"] == uid and len(session["csrf_token"]) > 20)
token = session["csrf_token"]

# ---- security
r = send(asha, entry(A))
check("Without the security code the request is rejected as JSON (400)", r.status_code == 400 and r.get_json() == {"error": "csrf"})
r = send(asha, entry(A), token="not-a-real-token")
check("A wrong security code is rejected", r.status_code == 400)
check("Nothing was saved by those", rows(A) == [])
r = asha.post("/api/transactions", data="not json", headers={"X-CSRFToken": token, "Content-Type": "text/plain"})
check("A request that isn't JSON is rejected", r.status_code == 400)
check("A JSON list instead of an object is rejected", send(asha, [1, 2], token).status_code == 400)

# ---- adding
first = entry(A)
r = send(asha, first, token)
check("A valid entry is created (201) and returns its ID", r.status_code == 201 and r.get_json()["duplicate"] is False and isinstance(r.get_json()["id"], int))
check("It is saved exactly as sent", rows(A) == [("expense", "12.50", "Queued lunch", today().isoformat())])
r = send(asha, first, token)
check("Sending the same entry again does not add it twice (200, duplicate)", r.status_code == 200 and r.get_json()["duplicate"] is True and len(rows(A)) == 1)
r = send(asha, entry(A, kind="income", amount=2500, category_id=cat(A, "Salary", "income"), description=None), token)
check("Income works, numbers are accepted as well as text, and a note is optional", r.status_code == 201 and rows(A)[-1] == ("income", "2500.00", None, today().isoformat()))
with app.app_context():
    check("Two receipts exist, one per entry", SyncReceipt.query.count() == 2)

# ---- the receipt survives deleting the transaction (so a late retry can't bring it back)
with app.app_context():
    t = Transaction.query.filter_by(description="Queued lunch").one()
    db.session.delete(t); db.session.commit()
r = send(asha, first, token)
check("After deleting it, a late retry of the same entry does NOT bring it back", r.status_code == 200 and r.get_json()["duplicate"] is True and all(x[2] != "Queued lunch" for x in rows(A)))

# ---- mistakes
def bad(message_part, **overrides):
    before = len(rows(A))
    r = send(asha, entry(A, **overrides), token)
    body = r.get_json()
    return r.status_code == 400 and message_part in body["error"] and len(rows(A)) == before

check("Missing client_id is rejected", send(asha, {k: v for k, v in entry(A).items() if k != "client_id"}, token).status_code == 400)
check("A client_id that isn't a UUID is rejected", send(asha, entry(A, client_id="abc"), token).status_code == 400)
check("Bad kind is rejected", bad("expense or income", kind="transfer"))
check("Amount 0 is rejected with the normal message", bad("greater than zero", amount="0"))
check("Amount with 3 decimals is rejected", bad("2 decimal places", amount="1.234"))
check("Non-number amount is rejected", bad("Enter an amount like", amount="abc"))
check("Too-large amount is rejected", bad("too large", amount="100000000"))
check("Missing amount is rejected", bad("Enter an amount", amount=None))
check("Future date is rejected", bad("future", date=(today() + timedelta(days=30)).isoformat()))
check("Malformed date is rejected", bad("valid date", date="12/31/2026"))
check("Old date is rejected", bad("2000", date="1999-01-01"))
check("An income category can't be used for an expense", bad("Choose a category", category_id=cat(A, "Salary", "income")))
check("A note over 200 characters is rejected", bad("200 characters", description="x" * 201))
r = send(asha, entry(A, amount="0"), token)
check("Errors list each problem by field", r.get_json()["errors"] == {"amount": ["Enter an amount greater than zero."]})
check("A rejected entry leaves no receipt behind, so it can be corrected and resent",
      send(asha, entry(A, client_id=(cid := str(uuid.uuid4())), amount="0"), token).status_code == 400
      and send(asha, entry(A, client_id=cid, amount="9"), token).status_code == 201)

# ---- privacy
ben = app.test_client(); signup(ben, "Ben", "ben@example.com"); B = "ben@example.com"
btoken = ben.get("/api/session").get_json()["csrf_token"]
r = send(ben, entry(B, category_id=cat(A, "Food")), btoken)
check("Ben can't file a transaction under Asha's category", r.status_code == 400 and rows(B) == [])
r = send(ben, first, btoken)
check("Ben sending Asha's entry ID gets a fresh entry, not Asha's receipt", r.status_code == 400 or r.get_json()["duplicate"] is False)
own = entry(B); r1 = send(ben, own, btoken)
check("Ben can send his own entries", r1.status_code == 201 and len(rows(B)) == 1)
check("Asha's own list didn't change (still her 2 entries)", len(rows(A)) == 2)
check("The same client_id used by two different people makes two separate transactions",
      send(asha, entry(A, client_id=own["client_id"]), token).status_code == 201)

# ---- the new transactions show up in the normal pages
html = asha.get("/transactions").get_data(as_text=True)
check(
    "Synced entries appear on the Transactions page",
    "$2,500.00" in html
    and "$9.00" in html
    and html.count('<span class="txn__title" title="Queued lunch">Queued lunch</span>') == 2,
)

finish()
