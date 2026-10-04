import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import click
from flask import Flask, jsonify, render_template, request
from flask_login import current_user
from flask_wtf.csrf import CSRFError
from sqlalchemy import inspect, text
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from config import DEV_SECRET_KEY, Config, ProductionConfig
from currency_utils import format_money
from extensions import csrf, db, limiter, login_manager, migrate
from routes.account import account
from routes.accounts_bp import accounts_bp
from routes.api import api
from routes.auth import auth
from routes.budgets import budgets
from routes.categories import categories
from routes.dashboard import dashboard
from routes.notifications import notifications_bp
from routes.pwa import pwa
from routes.receipt import receipt_bp
from routes.recurring import recurring_bp
from routes.transactions import transactions

# What people are told when something goes wrong (never technical details).
ERROR_PAGES = {
    400: ("That didn't work", "Your page had been open for a while, so it expired. Go back, refresh the page and try again."),
    404: ("Page not found", "We couldn't find that page. It may have been moved or deleted."),
    405: ("That isn't allowed here", "That action isn't available on this page."),
    413: ("That's too big", "The information sent was larger than this app accepts."),
    429: ("Too many attempts", "You've tried that a few times in a row. Please wait a minute and try again."),
    500: ("Something went wrong", "It's our fault, not yours. Your data is safe. Please try again in a moment."),
}


def choose_config():
    return ProductionConfig if os.environ.get("APP_ENV") == "production" else Config


def create_app(config_class=None):
    config_class = config_class or choose_config()
    app = Flask(__name__)
    app.config.from_object(config_class)

    if issubclass(config_class, ProductionConfig):
        secret = app.config["SECRET_KEY"]
        if secret == DEV_SECRET_KEY or len(secret) < 32:
            raise RuntimeError(
                "Online, SECRET_KEY must be set to a long random value (at least 32 characters). See DEPLOY.md."
            )
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if app.config["TRUST_PROXY"]:
        # Behind the host's front server: believe it about the visitor's address and about https.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)  # batch mode lets SQLite change tables too
    login_manager.init_app(app)
    csrf.init_app(app)  # blocks forged form submissions from other sites
    limiter.init_app(app)

    app.register_blueprint(auth)
    app.register_blueprint(dashboard)
    app.register_blueprint(account)
    app.register_blueprint(transactions)
    app.register_blueprint(budgets)
    app.register_blueprint(categories)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(recurring_bp)
    app.register_blueprint(receipt_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(pwa)
    app.register_blueprint(api)

    @app.context_processor
    def inject_app_names():
        return {"app_name": app.config["APP_NAME"], "app_short_name": app.config["APP_SHORT_NAME"]}

    # ------------------------------------------------------------ friendly errors
    def error_response(status):
        if request.path.startswith("/api/"):
            return jsonify(error=ERROR_PAGES.get(status, ("Error", ""))[0]), status
        title, message = ERROR_PAGES.get(status, ("Something went wrong", "Please try again."))
        return render_template("error.html", status=status, title=title, message=message), status

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "csrf"}), 400
        return error_response(400)

    @app.errorhandler(HTTPException)
    def http_error(error):
        if error.code in ERROR_PAGES:
            return error_response(error.code)
        return error

    if not app.debug:
        # Only outside of local development: catch anything we didn't plan for, log it for the
        # owner, and show a calm page. While developing (debug=True), an unhandled error instead
        # shows Flask's normal interactive debugger, which is far more useful for fixing it.
        @app.errorhandler(Exception)
        def unexpected_error(error):
            app.logger.exception("Unhandled error on %s %s", request.method, request.path)
            db.session.rollback()
            return error_response(500)

    # ------------------------------------------------------------ headers on every response
    @app.after_request
    def add_headers(response):
        if response.mimetype == "text/html":
            # Ask browsers not to keep copies of pages, so someone using the Back button
            # on a shared device can't see the last person's money after they sign out.
            response.headers["Cache-Control"] = "no-store"
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")  # nobody can show this app inside their own page
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=(), payment=()")
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if app.config["SEND_HSTS"]:
            headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    @app.template_filter("money")
    def money(amount):
        """{{ 1500|money }} -> the amount in the signed-in person's currency, e.g. ₹1,500.00"""
        return format_money(amount, current_user.currency, current_user.country)

    # ------------------------------------------------------------ health check
    @app.route("/healthz")
    @limiter.exempt
    def healthz():
        """Hosts (and you) can call this to see if the app and its database are working."""
        try:
            db.session.execute(text("SELECT 1"))
        except Exception:
            app.logger.exception("Health check: the database is not reachable")
            return jsonify(status="database unavailable"), 503
        return jsonify(status="ok")

    # ------------------------------------------------------------ backups
    @app.cli.command("backup")
    @click.option("--folder", default="backups", help="Where to put the copy.")
    def backup(folder):
        """Save a copy of the database (SQLite) with today's date."""
        url = db.engine.url
        if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
            raise click.ClickException("This command copies SQLite databases. For other databases, use your host's backups.")
        target = Path(folder)
        target.mkdir(parents=True, exist_ok=True)
        destination = target / f"finance-{datetime.now():%Y%m%d-%H%M%S}.db"
        source = sqlite3.connect(url.database)
        copy = sqlite3.connect(destination)
        with copy:
            source.backup(copy)  # a safe copy, even while the app is being used
        copy.close()
        source.close()
        click.echo(f"Saved {destination}")


    # Locally the app creates its own tables. Online, migrations do it (see DEPLOY.md).
    if app.config["AUTO_CREATE_TABLES"]:
        with app.app_context():
            db.create_all()
            _upgrade_local_schema()

    return app


def _upgrade_local_schema():
    """Bring older local SQLite databases up to the current model shape.

    Development databases are created with ``create_all`` and do not run Alembic
    automatically, so newly added columns need a small, idempotent upgrade.
    Production deployments continue to use the migration above.
    """
    if db.engine.url.get_backend_name() != "sqlite":
        return
    inspector = inspect(db.engine)
    transaction_columns = {column["name"] for column in inspector.get_columns("transaction")}
    if "source_fingerprint" not in transaction_columns:
        db.session.execute(text("ALTER TABLE \"transaction\" ADD COLUMN source_fingerprint VARCHAR(64)"))
    if "source_account_number" not in transaction_columns:
        db.session.execute(text("ALTER TABLE \"transaction\" ADD COLUMN source_account_number VARCHAR(40)"))
    if "import_batch" not in inspector.get_table_names():
        db.session.execute(text(
            "CREATE TABLE import_batch ("
            "id VARCHAR(64) PRIMARY KEY, user_id INTEGER NOT NULL, "
            "rows_json TEXT NOT NULL, created_at DATETIME NOT NULL, "
            "FOREIGN KEY(user_id) REFERENCES user (id))"
        ))
    db.session.commit()


if __name__ == "__main__":
    create_app().run()  # debug mode comes from config (Config.DEBUG = True), not hardcoded here
