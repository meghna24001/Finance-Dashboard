"""Small helpers shared by the test scripts."""
import html as htmllib
import re

passed = 0


def check(label, condition):
    global passed
    print(("PASS  " if condition else "FAIL  ") + label)
    assert condition, label
    passed += 1


def finish():
    print(f"\nAll {passed} checks passed.")


def text(response):
    return response.get_data(as_text=True)


def token(client, url):
    """Every form has a hidden security code. Read it from a page, like a browser does."""
    return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', text(client.get(url))).group(1)


def signup(client, name="Asha Rao", email="asha@example.com", country="US"):
    data = {"name": name, "email": email, "country": country,
            "password": "first-password", "confirm_password": "first-password",
            "csrf_token": token(client, "/register")}
    return client.post("/register", data=data)


def post(client, url, data=None, token_from=None, follow=True):
    """Submit a form the way a browser would (including the security code)."""
    data = dict(data or {})
    data["csrf_token"] = token(client, token_from or url)
    return client.post(url, data=data, follow_redirects=follow)


def flash_text(html):
    """The text of the one-time message at the top of the page (empty if none)."""
    m = re.search(r'<p class="flash[^"]*"[^>]*>(.*?)</p>', html, re.S)
    return htmllib.unescape(m.group(1).strip()) if m else ""
