"""Checks what matters once the app is online: safe settings, secure headers, friendly errors,
login rate limits, migrations, the health check and backups.
Uses temporary files and databases, so your real data is never touched."""
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

import flask_migrate
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

import config as config_module
from app import choose_config, create_app
from config import Config, ProductionConfig, TestConfig
from extensions import db
from tests.helpers import check, finish, text
from models import User

HERE = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp())
GOOD_KEY = "k" * 48


def prod_config(name="prod.db", **extra):
    attrs = {"SECRET_KEY": GOOD_KEY, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{TMP / name}", "AUTO_CREATE_TABLES": False, "RATELIMIT_ENABLED": False}
    attrs.update(extra)
    return type("Prod", (ProductionConfig,), attrs)


def token(client, url, **kw):
    return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', text(client.get(url, **kw))).group(1)


# ================================================================ settings
for bad in ["dev-only-change-me", "too-short"]:
    try:
        create_app(type("P", (ProductionConfig,), {"SECRET_KEY": bad, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"}))
        refused = False
    except RuntimeError as error:
        refused = "SECRET_KEY" in str(error)
    check(f"Online, a weak secret key ({bad!r}) is refused", refused)
check("Online, a long random secret key is accepted", create_app(prod_config()) is not None)

os.environ["APP_ENV"] = "production"; check("APP_ENV=production selects the online settings", choose_config() is ProductionConfig)
os.environ.pop("APP_ENV"); check("Without it, the local settings are used", choose_config() is Config)

os.environ["DATABASE_URL"] = "postgres://user:pw@host:5432/db"
check("An old-style postgres:// address is converted for SQLAlchemy", config_module.database_url() == "postgresql://user:pw@host:5432/db")
os.environ["DATABASE_URL"] = "postgresql://user:pw@host/db"
check("A modern postgresql:// address is left alone", config_module.database_url() == "postgresql://user:pw@host/db")
os.environ.pop("DATABASE_URL")
check("With no DATABASE_URL a local file is used", config_module.database_url() == "sqlite:///finance.db")
check("Online settings never create tables automatically; local ones do", ProductionConfig.AUTO_CREATE_TABLES is False and Config.AUTO_CREATE_TABLES is True)

# ================================================================ migrations
app = create_app(prod_config("migrated.db"))
with app.app_context():
    check("Before migrating, the online database is empty (nothing was auto-created)", inspect(db.engine).get_table_names() == [])
    flask_migrate.upgrade(directory=str(HERE / "migrations"))
    tables = set(inspect(db.engine).get_table_names())
    check("Migrating creates every table", {"user", "category", "transaction", "budget", "sync_receipt", "alembic_version"} <= tables)
    with db.engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), db.metadata)
    check("The migrated tables match the app's models exactly (no differences)", differences == [])
    flask_migrate.downgrade(directory=str(HERE / "migrations"), revision="base")
    check("Migrations can also be undone", set(inspect(db.engine).get_table_names()) <= {"alembic_version"})
    flask_migrate.upgrade(directory=str(HERE / "migrations"))
    check("...and applied again", "user" in inspect(db.engine).get_table_names())
from alembic.script import ScriptDirectory
from alembic.config import Config as AlembicConfig
script = ScriptDirectory(str(HERE / "migrations"))
check("There is exactly one migration history (a single 'head')", len(script.get_heads()) == 1)

# ================================================================ the whole app on the online settings, over https
HTTPS = "https://finance.example.com"
client = app.test_client()
ref = {"Referer": HTTPS + "/register"}
r = client.post("/register", base_url=HTTPS, headers=ref, data={"name": "Asha", "email": "asha@example.com", "country": "IN", "password": "first-password", "confirm_password": "first-password", "csrf_token": token(client, "/register", base_url=HTTPS)})
check("Signing up works on the online settings, on a database built by migrations", r.status_code == 302)
cookies = " ".join(r.headers.getlist("Set-Cookie"))
check("The login cookie is Secure, HttpOnly and SameSite=Lax", "Secure" in cookies and "HttpOnly" in cookies and "SameSite=Lax" in cookies)
page = client.get("/dashboard", base_url=HTTPS)
check("The signed-in Home page loads over https", page.status_code == 200 and "Hello, Asha" in text(page))
check("Strict-Transport-Security tells browsers to always use https", page.headers["Strict-Transport-Security"] == "max-age=31536000")
r = client.post("/profile/details", base_url=HTTPS, data={"name": "Hacker", "country": "US", "csrf_token": token(client, "/profile", base_url=HTTPS)})
check("A form submitted without a matching Referer over https is refused (400)", r.status_code == 400 and "expired" in text(r))
check("...and Asha's name was not changed", "Hello, Asha" in text(client.get("/dashboard", base_url=HTTPS)))

# ================================================================ headers
dev = create_app(TestConfig).test_client()
for label, response in [("a page", dev.get("/login")), ("a static file", dev.get("/static/css/style.css")), ("the API", dev.get("/api/ping")), ("the health check", dev.get("/healthz"))]:
    h = response.headers
    check(f"Security headers are on {label}", h["X-Content-Type-Options"] == "nosniff" and h["X-Frame-Options"] == "DENY" and h["Referrer-Policy"] == "strict-origin-when-cross-origin" and "camera=(self)" in h["Permissions-Policy"] and "microphone=()" in h["Permissions-Policy"] and h["Cross-Origin-Opener-Policy"] == "same-origin")
check("Local settings don't send HSTS (it would lock you into https on localhost)", "Strict-Transport-Security" not in dev.get("/login").headers)
check("Pages are still 'no-store', and the service worker still 'no-cache'", dev.get("/login").headers["Cache-Control"] == "no-store" and dev.get("/sw.js").headers["Cache-Control"] == "no-cache")

# ================================================================ friendly errors
r = dev.get("/no-such-page")
check("An unknown address shows a friendly page (404), not technical details", r.status_code == 404 and "Page not found" in text(r) and "Traceback" not in text(r) and 'href="/"' in text(r))
r = dev.get("/logout")
check("A wrong method shows a friendly page (405)", r.status_code == 405 and "isn&#39;t allowed" in text(r) or "isn't allowed" in text(r))
r = dev.post("/login", data={"email": "a@b.c", "password": "x"})
check("A form without its security code shows a friendly page (400)", r.status_code == 400 and "expired" in text(r))
r = dev.get("/api/nope")
check("Errors on /api/ are JSON, not web pages", r.status_code == 404 and r.get_json() == {"error": "Page not found"})
r = dev.post("/login", data="x" * 1_100_000, content_type="application/x-www-form-urlencoded")
check("Something over 1 MB is refused (413) with a friendly page", r.status_code == 413 and "too big" in text(r))

boom_app = create_app(TestConfig)
@boom_app.route("/boom")
def boom():
    db.session.add(User(email="half@example.com", name="Half", password_hash="x", country="US", currency="USD"))
    db.session.flush()
    raise ValueError("secret internal detail")
boom_client = boom_app.test_client()
with mock.patch.object(boom_app.logger, "exception") as logged:
    r = boom_client.get("/boom")
check("An unexpected crash shows a calm 500 page with no internal details", r.status_code == 500 and "Something went wrong" in text(r) and "secret internal detail" not in text(r) and "ValueError" not in text(r))
check("...and the crash is recorded in the log for the owner", logged.called)
with boom_app.app_context():
    check("...and the half-finished change was rolled back", User.query.count() == 0)
check("The app keeps working after a crash", boom_client.get("/login").status_code == 200)

# ================================================================ health check
r = dev.get("/healthz")
check("The health check says ok when the database works", r.status_code == 200 and r.get_json() == {"status": "ok"})
broken_app = create_app(prod_config(SQLALCHEMY_DATABASE_URI="sqlite:////nonexistent-folder/x.db"))
with mock.patch.object(broken_app.logger, "exception"):   # keep the expected error out of the test output
    r = broken_app.test_client().get("/healthz")
check("...and 503 when the database can't be reached", r.status_code == 503 and r.get_json()["status"] == "database unavailable")

# ================================================================ rate limits
limited = create_app(type("L", (TestConfig,), {"RATELIMIT_ENABLED": True, "CLIENT_IP_HEADER": "X-Real-IP"})).test_client()
def try_login(ip):
    """Like a real password-guesser: fetch the sign-in page for its security code, then try a password."""
    code = token(limited, "/login", headers={"X-Real-IP": ip})
    return limited.post("/login", data={"email": "nobody@example.com", "password": "wrong-password", "csrf_token": code}, headers={"X-Real-IP": ip})
codes = [try_login("203.0.113.1").status_code for _ in range(12)]
check("Login allows 10 tries a minute, then says 'Too many attempts' (429)", codes[:10] == [200] * 10 and codes[10:] == [429, 429])
r = try_login("203.0.113.1")
check("...with a friendly page", r.status_code == 429 and "Too many attempts" in text(r))
check("A different person (another address) isn't blocked", try_login("203.0.113.2").status_code == 200)
check("Just looking at the sign-in page is never limited", all(limited.get("/login", headers={"X-Real-IP": "203.0.113.1"}).status_code == 200 for _ in range(30)))
check("The health check is never limited", all(limited.get("/healthz", headers={"X-Real-IP": "203.0.113.1"}).status_code == 200 for _ in range(30)))
reg = [limited.post("/register", data={"name": "x", "csrf_token": token(limited, "/register", headers={"X-Real-IP": "203.0.113.9"})}, headers={"X-Real-IP": "203.0.113.9"}).status_code for _ in range(7)]
check("Sign-ups are limited harder: 5 a minute", reg[:5] == [200] * 5 and reg[5:] == [429, 429])

# ================================================================ behind the host's front server
proxied = create_app(type("X", (TestConfig,), {"TRUST_PROXY": True}))
@proxied.route("/whoami")
def whoami():
    from flask import jsonify, request
    return jsonify(ip=request.remote_addr, secure=request.is_secure, host=request.host)
r = proxied.test_client().get("/whoami", headers={"X-Forwarded-For": "203.0.113.77", "X-Forwarded-Proto": "https", "X-Forwarded-Host": "finance.example.com"})
check("With TRUST_PROXY, the real visitor address, https and host are taken from the front server", r.get_json() == {"ip": "203.0.113.77", "secure": True, "host": "finance.example.com"})
plain = create_app(TestConfig)
@plain.route("/whoami")
def whoami2():
    from flask import jsonify, request
    return jsonify(ip=request.remote_addr, secure=request.is_secure)
r = plain.test_client().get("/whoami", headers={"X-Forwarded-For": "203.0.113.77", "X-Forwarded-Proto": "https"})
check("Without TRUST_PROXY, those headers are ignored (they could be faked)", r.get_json()["ip"] != "203.0.113.77" and r.get_json()["secure"] is False)

# ================================================================ backups
file_app = create_app(type("F", (TestConfig,), {"SQLALCHEMY_DATABASE_URI": f"sqlite:///{TMP / 'live.db'}"}))
with file_app.app_context():
    db.session.add(User(email="keep@example.com", name="Keep", password_hash="x", country="US", currency="USD")); db.session.commit()
runner = file_app.test_cli_runner()
result = runner.invoke(args=["backup", "--folder", str(TMP / "backups")])
copies = list((TMP / "backups").glob("finance-*.db"))
check("The backup command saves a dated copy", result.exit_code == 0 and "Saved" in result.output and len(copies) == 1)
check("The copy contains the data", sqlite3.connect(copies[0]).execute("select email from user").fetchall() == [("keep@example.com",)])
result = create_app(TestConfig).test_cli_runner().invoke(args=["backup", "--folder", str(TMP / "nope")])
check("The backup command explains itself for databases it can't copy", result.exit_code != 0 and "SQLite" in result.output)

finish()
