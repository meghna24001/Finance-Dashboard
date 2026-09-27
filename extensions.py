from flask import current_app, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()  # keeps track of changes to the database's structure


def client_ip():
    """Who is asking? Used to count attempts per person, not per website visitor as a whole."""
    header = current_app.config.get("CLIENT_IP_HEADER")
    if header:
        value = request.headers.get(header, "")
        if value:
            return value.split(",")[0].strip()
    return get_remote_address()


limiter = Limiter(key_func=client_ip)
login_manager = LoginManager()
csrf = CSRFProtect()

# Where to send people who open a page that needs login.
login_manager.login_view = "auth.login"
login_manager.login_message = "Sign in to continue."
login_manager.login_message_category = "info"
