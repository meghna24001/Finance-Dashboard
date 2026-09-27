import os

from dotenv import load_dotenv

load_dotenv()  # reads a .env file if one exists; does nothing otherwise

DEV_SECRET_KEY = "dev-only-change-me"


def database_url():
    """Where the data lives. Locally it's a file; online it can be a proper database server."""
    url = os.environ.get("DATABASE_URL", "sqlite:///finance.db")
    if url.startswith("postgres://"):  # some hosts still use the old spelling
        url = "postgresql://" + url[len("postgres://"):]
    return url


class Config:
    """Settings for working on your own computer."""

    APP_NAME = "FinSight"
    APP_SHORT_NAME = "FinSight"  # the name under the icon on a phone home screen
    DEBUG = True  # shows Flask's interactive debugger in the browser when something crashes

    # Used by Flask to sign login sessions. Online, a real secret is required (see ProductionConfig).
    SECRET_KEY = os.environ.get("SECRET_KEY", DEV_SECRET_KEY)

    # SQLite stores the whole database in one file (created in the "instance" folder).
    SQLALCHEMY_DATABASE_URI = database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Locally the app creates its own tables. Online, tables are made by migrations instead
    # (see DEPLOY.md), so the structure can change later without losing anyone's data.
    AUTO_CREATE_TABLES = os.environ.get("AUTO_CREATE_TABLES", "1") == "1"

    # Login cookie safety.
    SESSION_COOKIE_HTTPONLY = True      # JavaScript can't read the cookie
    SESSION_COOKIE_SAMESITE = "Lax"     # other sites can't send it along with their requests
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("COOKIE_SECURE") == "1"
    REMEMBER_COOKIE_SECURE = os.environ.get("COOKIE_SECURE") == "1"

    MAX_CONTENT_LENGTH = 5_000_000      # statement imports need room for multi-page PDFs

    # Slowing down people who try to guess passwords.
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URI = "memory://"
    # Some hosts put the visitor's real address in a header (PythonAnywhere: X-Real-IP).
    CLIENT_IP_HEADER = os.environ.get("CLIENT_IP_HEADER", "")

    # Set TRUST_PROXY=1 on hosts where a front server passes on the real address and https (Render, Railway...).
    TRUST_PROXY = os.environ.get("TRUST_PROXY") == "1"
    SEND_HSTS = False


class ProductionConfig(Config):
    """Settings for the app when it is online, where real people use it."""

    AUTO_CREATE_TABLES = os.environ.get("AUTO_CREATE_TABLES", "0") == "1"
    DEBUG = False  # never show the interactive debugger (or anyone's data in a traceback) online
    SESSION_COOKIE_SECURE = True        # cookies only travel over https
    REMEMBER_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = "https"
    SEND_HSTS = True                    # tell browsers to always use https for this site


class TestConfig(Config):
    """Used by the test scripts: a throwaway database that lives only in memory."""

    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    AUTO_CREATE_TABLES = True
    DEBUG = False  # tests check the friendly error page, not the interactive debugger
    RATELIMIT_ENABLED = False
