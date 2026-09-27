"""Small JSON endpoints used by the app's own scripts (never by people directly)."""
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request
from flask_login import current_user
from flask_wtf.csrf import generate_csrf

from finance import today
from models import Category, SyncReceipt, Transaction, db

api = Blueprint("api", __name__, url_prefix="/api")


def no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@api.route("/ping")
def ping():
    """The app calls this to find out whether the server can be reached."""
    return no_store(jsonify(ok=True))


@api.route("/session")
def session():
    """Return the user's ID and a CSRF token for API operations."""
    if not current_user.is_authenticated:
        return no_store(jsonify(error="unauthorized")), 401
    return no_store(jsonify(user_id=current_user.id, csrf_token=generate_csrf()))


@api.route("/transactions", methods=["POST"])
def add_transaction():
    """Endpoint for syncing offline transactions."""
    if not current_user.is_authenticated:
        return no_store(jsonify(error="unauthorized")), 401

    if not request.is_json:
        return no_store(jsonify(error="JSON required")), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return no_store(jsonify(error="JSON object required")), 400

    client_id = data.get("client_id")
    if not client_id:
        return no_store(jsonify(error="client_id required")), 400

    try:
        uuid.UUID(str(client_id))
    except (ValueError, TypeError):
        return no_store(jsonify(error="client_id must be a UUID")), 400

    # Deduplication check
    existing = SyncReceipt.query.filter_by(user_id=current_user.id, client_id=str(client_id)).first()
    if existing:
        return no_store(jsonify(duplicate=True, id=existing.transaction_id)), 200

    errors = {}

    kind = data.get("kind")
    if kind not in ("expense", "income"):
        return no_store(jsonify(error="kind must be expense or income")), 400

    amount_val = data.get("amount")
    if amount_val is None or str(amount_val).strip() == "":
        errors["amount"] = ["Enter an amount."]
    else:
        try:
            amt_str = str(amount_val).strip()
            if "." in amt_str and len(amt_str.split(".")[1]) > 2:
                errors["amount"] = ["Use at most 2 decimal places."]
            else:
                amt_dec = Decimal(amt_str)
                if amt_dec <= 0:
                    errors["amount"] = ["Enter an amount greater than zero."]
                elif amt_dec >= Decimal("100000000"):
                    errors["amount"] = ["That amount is too large."]
        except (InvalidOperation, ValueError):
            errors["amount"] = ["Enter an amount like 250 or 250.50."]

    cat_id = data.get("category_id")
    category = None
    if cat_id is not None:
        try:
            category = Category.query.filter_by(id=int(cat_id), user_id=current_user.id).first()
        except (ValueError, TypeError):
            category = None
    if not category or category.type != kind:
        errors["category_id"] = ["Choose a category."]

    date_val = data.get("date")
    parsed_date = None
    if not date_val:
        errors["date"] = ["Choose a date."]
    else:
        try:
            parsed_date = datetime.strptime(str(date_val), "%Y-%m-%d").date()
            if parsed_date < date(2000, 1, 1):
                errors["date"] = ["Choose a date from the year 2000 onwards."]
            elif parsed_date > today():
                errors["date"] = ["Choose a date that isn't in the future."]
        except ValueError:
            errors["date"] = ["Enter a valid date."]

    description = data.get("description")
    if description:
        description = str(description).strip()
        if len(description) > 200:
            errors["description"] = ["Use at most 200 characters."]
    else:
        description = None

    if errors:
        first_field = next(iter(errors))
        first_msg = errors[first_field][0]
        return no_store(jsonify(error=first_msg, errors=errors)), 400

    amt_final = Decimal(str(amount_val).strip())
    t = Transaction(
        user_id=current_user.id,
        amount=amt_final,
        type=kind,
        category_id=category.id,
        date=parsed_date,
        description=description,
    )
    db.session.add(t)
    db.session.flush()

    receipt = SyncReceipt(
        user_id=current_user.id,
        client_id=str(client_id),
        transaction_id=t.id,
    )
    db.session.add(receipt)
    db.session.commit()

    return no_store(jsonify(duplicate=False, id=t.id)), 201
