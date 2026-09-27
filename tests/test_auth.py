"""Simulates real people using the sign up / sign in / sign out pages.
Uses a throwaway in-memory database, so your real data is never touched."""
import re

from app import create_app
from config import TestConfig
from models import db, User

app = create_app(TestConfig)
passed = 0


def check(label, condition):
    global passed
    print(("PASS  " if condition else "FAIL  ") + label)
    assert condition, label
    passed += 1


def csrf_token(client, url):
    html = client.get(url).get_data(as_text=True)
    return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html).group(1)


def register(client, **overrides):
    data = {"name": "Asha", "email": "asha@example.com", "country": "US",
            "password": "correct-horse", "confirm_password": "correct-horse"}
    data.update(overrides)
    data["csrf_token"] = csrf_token(client, "/register")
    return client.post("/register", data=data)


def login(client, email, password, url="/login", **extra):
    data = {"email": email, "password": password, "csrf_token": csrf_token(client, url)}
    data.update(extra)
    return client.post(url, data=data)


def logout(client):
    return client.post("/logout", data={"csrf_token": csrf_token(client, "/dashboard")})


# ---- pages load
c = app.test_client()
check("GET / sends visitors to /login", c.get("/").headers["Location"].endswith("/login"))
r = c.get("/register")
check("Register page loads with a country dropdown", r.status_code == 200 and b"Select your country" in r.data and b'value="IN"' in r.data)
check("Login page loads", c.get("/login").status_code == 200)

# ---- security basics
check("Form without CSRF token is rejected (400)", c.post("/register", data={"name": "x"}).status_code == 400)
check("Dashboard needs login (redirects with ?next=)", "/login?next=%2Fdashboard" in c.get("/dashboard").headers["Location"])
check("Logout by plain link (GET) is not allowed (405)", c.get("/logout").status_code == 405)

# ---- registration errors
r = register(c, password="short", confirm_password="short")
check("Short password is rejected", b"Use 8 to 128 characters." in r.data)
r = register(c, confirm_password="different-pass")
check("Mismatched passwords are rejected", b"Passwords don&#39;t match." in r.data or b"Passwords don't match." in r.data)
r = register(c, email="not-an-email")
check("Invalid email is rejected", b"Enter a valid email address." in r.data)
r = register(c, country="")
check("Missing country is rejected", b"Choose your country." in r.data)
r = register(c, name="  ")
check("Blank name is rejected", b"Enter your name." in r.data)
with app.app_context():
    check("Nothing was saved by the failed attempts", User.query.count() == 0)

# ---- successful registration
r = register(c, email="  Asha@Example.COM ")
check("Valid registration redirects to /dashboard", r.status_code == 302 and r.headers["Location"].endswith("/dashboard"))
page = c.get("/dashboard")
check("New user is already signed in and sees their name", page.status_code == 200 and b"Hello, Asha" in page.data)
check("US country shows amounts in dollars", b"$0.00" in page.data)
with app.app_context():
    u = User.query.one()
    check("Email saved lowercase and trimmed", u.email == "asha@example.com")
    check("Country and currency saved (US, USD)", (u.country, u.currency) == ("US", "USD"))
    check("Password is stored hashed, not as typed", "correct-horse" not in u.password_hash and u.password_hash.startswith("scrypt:"))

# ---- signed-in visitors skip the forms
check("Signed-in user visiting /login goes to dashboard", c.get("/login").headers["Location"].endswith("/dashboard"))

# ---- logout
r = logout(c)
check("Logout redirects to /login", r.status_code == 302 and r.headers["Location"].endswith("/login"))
check("After logout the dashboard is locked again", c.get("/dashboard").status_code == 302)
check("'You're signed out' message shown", b"signed out" in c.get("/login").data)

# ---- duplicate email (any capitalisation)
r = register(app.test_client(), email="ASHA@example.com")
check("Duplicate email is rejected", b"already exists" in r.data)
with app.app_context():
    check("Still only one account", User.query.count() == 1)

# ---- login
r = login(c, "asha@example.com", "wrong-password")
wrong_pw = r.get_data(as_text=True)
check("Wrong password shows a generic error", r.status_code == 200 and "Email or password is incorrect." in wrong_pw)
r = login(c, "nobody@example.com", "whatever123")
check("Unknown email shows the same error (no account-guessing)", "Email or password is incorrect." in r.get_data(as_text=True))
check("Still locked out after failed logins", c.get("/dashboard").status_code == 302)

r = login(c, "  ASHA@example.com", "correct-horse")
check("Correct login (any email capitalisation) works", r.status_code == 302 and r.headers["Location"].endswith("/dashboard"))
logout(c)

r = login(c, "asha@example.com", "correct-horse", url="/login?next=/dashboard")
check("Login returns you to the page you wanted", r.headers["Location"] == "/dashboard")
logout(c)
for bad in ["https://evil.example", "//evil.example", "/\\evil.example"]:
    r = login(c, "asha@example.com", "correct-horse", url="/login?next=" + bad)
    check(f"Unsafe next={bad!r} is ignored", r.headers["Location"].endswith("/dashboard") and "evil" not in r.headers["Location"])
    logout(c)

# ---- two people, two separate accounts
c2 = app.test_client()
register(c2, name="Ben", email="ben@example.com", country="JP")
page2 = c2.get("/dashboard")
check("Second user sees their own name and currency (yen)", b"Hello, Ben" in page2.data and "¥0".encode() in page2.data and b"Asha" not in page2.data)
check("First user's session is unaffected", login(c, "asha@example.com", "correct-horse").status_code == 302 and b"Hello, Asha" in c.get("/dashboard").data)

print(f"\nAll {passed} checks passed.")
