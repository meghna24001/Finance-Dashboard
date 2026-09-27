"""Simulates people using the profile page: edit details, change country, change password.
Uses a throwaway in-memory database, so your real data is never touched."""
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

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


def token(client, url="/profile"):
    html = client.get(url).get_data(as_text=True)
    return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html).group(1)


def signup(client, name, email, country):
    data = {"name": name, "email": email, "country": country,
            "password": "first-password", "confirm_password": "first-password"}
    data["csrf_token"] = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', client.get("/register").get_data(as_text=True)).group(1)
    return client.post("/register", data=data)


def save_details(client, **data):
    data["csrf_token"] = token(client)
    return client.post("/profile/details", data=data, follow_redirects=True)


def change_password(client, current, new, confirm):
    data = {"current_password": current, "new_password": new, "confirm_new_password": confirm, "csrf_token": token(client)}
    return client.post("/profile/password", data=data, follow_redirects=True)


def flash_text(html):
    """The text of the one-time message at the top of the page (empty if none)."""
    m = re.search(r'<p class="flash[^"]*"[^>]*>(.*?)</p>', html, re.S)
    return m.group(1).strip() if m else ""


def user(email):
    with app.app_context():
        u = User.query.filter_by(email=email).one()
        return u.name, u.country, u.currency


# ---- initials
u = User(name="Asha Rao"); check("Initials: 'Asha Rao' -> AR", u.initials == "AR")
u = User(name="asha"); check("Initials: 'asha' -> A", u.initials == "A")
u = User(name="Anna Maria Lopez"); check("Initials: 'Anna Maria Lopez' -> AL", u.initials == "AL")

# ---- access
anon = app.test_client()
check("Profile page needs login", anon.get("/profile").status_code == 302)
check("Saving details needs login", anon.post("/profile/details", data={}).status_code in (302, 400))

# ---- viewing
asha = app.test_client()
signup(asha, "Asha Rao", "asha@example.com", "IN")
page = asha.get("/profile")
html = page.get_data(as_text=True)
check("Profile page loads", page.status_code == 200)
check("Shows name, email, initials and member-since", "Asha Rao" in html and "asha@example.com" in html and ">AR<" in html and "Member since" in html)
check("Country dropdown has India selected", re.search(r'<option[^>]*selected[^>]*value="IN"|<option[^>]*value="IN"[^>]*selected', html) is not None)
check("Shows currency INR with ₹ sample", "INR" in html and "₹1,00,000.00" in html)
check("Email cannot be edited (no email input)", 'name="email"' not in html)
check("Dashboard top bar links to the profile", 'href="/profile"' in asha.get("/dashboard").get_data(as_text=True))

# ---- editing details
r = save_details(asha, name="  Asha R. Rao ", country="JP")
html = r.get_data(as_text=True)
check("Changing country to Japan saves name, country and currency", user("asha@example.com") == ("Asha R. Rao", "JP", "JPY"))
check("Message says currency changed and amounts are not converted", flash_text(html) == "Profile updated. Amounts now show in JPY. Existing amounts are not converted.")
check("Page now shows yen formatting", "¥100,000" in html)

r = save_details(asha, name="Asha R. Rao", country="FR")   # JPY -> EUR
r = save_details(asha, name="Asha Rao", country="DE")      # EUR -> EUR (same currency)
html = r.get_data(as_text=True)
check("Same-currency change gives a plain 'Profile updated.'", flash_text(html) == "Profile updated.")
check("Saved as Germany / EUR", user("asha@example.com") == ("Asha Rao", "DE", "EUR"))

r = save_details(asha, name="   ", country="DE")
check("Blank name is rejected and nothing changes", "Enter your name." in r.get_data(as_text=True) and user("asha@example.com")[0] == "Asha Rao")
r = save_details(asha, name="Asha Rao", country="ZZ")
check("Made-up country is rejected and nothing changes", r.status_code == 200 and user("asha@example.com")[1] == "DE")
check("Details form without CSRF token is rejected (400)", asha.post("/profile/details", data={"name": "Hacked", "country": "US"}).status_code == 400)
check("Name unchanged after rejected forgery", user("asha@example.com")[0] == "Asha Rao")

# ---- changing password
r = change_password(asha, "wrong-password", "second-password", "second-password")
check("Wrong current password is rejected", "isn&#39;t your current password" in r.get_data(as_text=True) or "isn't your current password" in r.get_data(as_text=True))
r = change_password(asha, "first-password", "short", "short")
check("Short new password is rejected", "Use 8 to 128 characters." in r.get_data(as_text=True))
r = change_password(asha, "first-password", "second-password", "different-password")
check("Mismatched new passwords are rejected", "Passwords don&#39;t match." in r.get_data(as_text=True) or "Passwords don't match." in r.get_data(as_text=True))
r = change_password(asha, "first-password", "first-password", "first-password")
check("Reusing the current password is rejected", "different from your current one" in r.get_data(as_text=True))
check("Password form without CSRF token is rejected (400)", asha.post("/profile/password", data={"current_password": "first-password", "new_password": "second-password", "confirm_new_password": "second-password"}).status_code == 400)

r = change_password(asha, "first-password", "second-password", "second-password")
check("Correct change shows 'Password updated.'", flash_text(r.get_data(as_text=True)) == "Password updated.")

# sign out, then check old vs new password
asha.post("/logout", data={"csrf_token": token(asha, "/dashboard")})


def try_login(client, password):
    data = {"email": "asha@example.com", "password": password,
            "csrf_token": re.search(r'name="csrf_token"[^>]*value="([^"]+)"', client.get("/login").get_data(as_text=True)).group(1)}
    return client.post("/login", data=data)


check("Old password no longer works", try_login(asha, "first-password").status_code == 200)
check("New password works", try_login(asha, "second-password").status_code == 302)

# ---- two people stay separate
ben = app.test_client()
signup(ben, "Ben Ito", "ben@example.com", "US")
save_details(ben, name="Ben I.", country="GB")
check("Ben's edit changed Ben", user("ben@example.com") == ("Ben I.", "GB", "GBP"))
check("Ben's edit did not touch Asha", user("asha@example.com") == ("Asha Rao", "DE", "EUR"))
check("Ben's profile page shows only his own details", "Ben I." in ben.get("/profile").get_data(as_text=True) and "asha@example.com" not in ben.get("/profile").get_data(as_text=True))

print(f"\nAll {passed} checks passed.")
