from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import uuid

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from finance import month_transactions, parse_month, shift_month, today, totals
from forms import TransactionForm
from bank_import import BankImportError as StatementImportError, parse_statement
from models import BankAccount, ImportBatch, Transaction

transactions = Blueprint("transactions", __name__, url_prefix="/transactions")

KINDS = ("expense", "income")


def own_transaction_or_404(transaction_id):
    """Find a transaction, but only if it belongs to the signed-in person.
    Someone else's transaction looks exactly like one that doesn't exist."""
    return Transaction.query.filter_by(id=transaction_id, user_id=current_user.id).first_or_404()


def month_link(day):
    return url_for("transactions.index", month=day.strftime("%Y-%m"))


@transactions.route("")
@login_required
def index():
    year, month = parse_month(request.args.get("month"))
    items = month_transactions(current_user.id, year, month)

    # Group the (already sorted) list by day, so each day gets a heading.
    days = []
    for item in items:
        if not days or days[-1]["date"] != item.date:
            days.append({"date": item.date, "items": []})
        days[-1]["items"].append(item)

    now = today()
    prev_year, prev_month = shift_month(year, month, -1)
    next_year, next_month = shift_month(year, month, 1)
    is_current_month = (year, month) == (now.year, now.month)

    return render_template(
        "transactions/index.html",
        days=days,
        summary=totals(items),
        month_label=date(year, month, 1).strftime("%B %Y"),
        month_key=f"{year}-{month:02d}",
        prev_month=f"{prev_year}-{prev_month:02d}",
        next_month=None if is_current_month else f"{next_year}-{next_month:02d}",
    )


@transactions.route("/new/<kind>", methods=["GET", "POST"])
@login_required
def new(kind):
    if kind not in KINDS:
        abort(404)

    form = TransactionForm(kind=kind)
    if not form.category_id.choices:
        flash(f"Add an {kind} category first.", "info")
        return redirect(url_for("categories.index"))

    if form.validate_on_submit():
        account_id = form.account_id.data if form.account_id.data else None
        item = Transaction(
            user_id=current_user.id,
            type=kind,
            amount=form.amount.data,
            category_id=form.category_id.data,
            date=form.date.data,
            payment_mode=form.payment_mode.data or "cash",
            upi_id=form.upi_id.data or None,
            account_id=account_id,
            receipt_path=form.receipt_path.data or None,
            description=form.description.data or None,
            source_account_number=form.source_account_number.data or None,
        )
        db.session.add(item)
        db.session.commit()
        flash(f"{kind.capitalize()} added.", "success")
        return redirect(month_link(item.date))

    if request.method == "GET":
        form.date.data = today()  # the browser replaces this with your own local date
    return render_template("transactions/form.html", form=form, kind=kind, item=None)


@transactions.route("/<int:transaction_id>/edit", methods=["GET", "POST"])
@login_required
def edit(transaction_id):
    item = own_transaction_or_404(transaction_id)
    form = TransactionForm(kind=item.type, obj=item)

    if form.validate_on_submit():
        item.amount = form.amount.data
        item.category_id = form.category_id.data
        item.date = form.date.data
        item.payment_mode = form.payment_mode.data or "cash"
        item.upi_id = form.upi_id.data or None
        item.account_id = form.account_id.data if form.account_id.data else None
        if form.receipt_path.data:
            item.receipt_path = form.receipt_path.data
        item.description = form.description.data or None
        item.source_account_number = form.source_account_number.data or None
        db.session.commit()
        flash("Changes saved.", "success")
        return redirect(month_link(item.date))

    if request.method == "GET":
        if item.account_id:
            form.account_id.data = item.account_id
        if item.payment_mode:
            form.payment_mode.data = item.payment_mode

    return render_template("transactions/form.html", form=form, kind=item.type, item=item)


@transactions.route("/<int:transaction_id>/delete", methods=["POST"])
@login_required
def delete(transaction_id):
    item = own_transaction_or_404(transaction_id)
    day = item.date
    db.session.delete(item)
    db.session.commit()
    flash("Transaction deleted.", "success")
    return redirect(month_link(day))


def _import_context():
    categories = sorted(current_user.categories, key=lambda c: (c.type, c.name.casefold()))
    accounts = BankAccount.query.filter_by(user_id=current_user.id, is_active=True).order_by(BankAccount.name).all()
    return categories, accounts


@transactions.route("/import", methods=["GET", "POST"])
@login_required
def import_statement():
    categories, accounts = _import_context()
    if request.method == "GET":
        return render_template("transactions/import.html", rows=None, batch=None, categories=categories, accounts=accounts)

    upload = request.files.get("statement")
    if not upload or not upload.filename:
        flash("Choose a PDF, XLS, or XLSX statement to import.", "error")
        return render_template("transactions/import.html", rows=None, batch=None, categories=categories, accounts=accounts)

    try:
        rows = parse_statement(upload.read(), request.form.get("password", ""), filename=upload.filename)
    except StatementImportError as error:
        flash(str(error), "error")
        return render_template("transactions/import.html", rows=None, batch=None, categories=categories, accounts=accounts)

    if not rows:
        flash("No readable transaction rows were found in that statement.", "error")
        return render_template("transactions/import.html", rows=None, batch=None, categories=categories, accounts=accounts)

    batch = ImportBatch(id=uuid.uuid4().hex, user_id=current_user.id)
    batch.set_rows(rows)
    db.session.add(batch)
    db.session.commit()
    existing = {
        fingerprint for (fingerprint,) in Transaction.query.filter_by(user_id=current_user.id)
        .with_entities(Transaction.source_fingerprint).all() if fingerprint
    }
    for row in rows:
        row["duplicate"] = row["fingerprint"] in existing
    return render_template("transactions/import.html", rows=rows, batch=batch, categories=categories, accounts=accounts)


@transactions.route("/import/<batch_id>/commit", methods=["POST"])
@login_required
def commit_import(batch_id):
    batch = ImportBatch.query.filter_by(id=batch_id, user_id=current_user.id).first_or_404()
    rows = batch.get_rows()
    categories, accounts = _import_context()
    category_ids = {c.id for c in categories}
    account_ids = {a.id for a in accounts}
    selected = set(request.form.getlist("selected"))
    imported = 0
    skipped = 0
    try:
        for index, row in enumerate(rows):
            if str(index) not in selected:
                continue
            try:
                amount = Decimal(row["amount"])
                category_id = int(request.form.get(f"category_{index}", "0") or 0)
                account_id = int(request.form.get(f"account_{index}", "0") or 0)
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError(f"Row {index + 1} has an invalid amount, category, or account.")
            if amount <= 0 or (category_id and category_id not in category_ids) or (account_id and account_id not in account_ids):
                raise ValueError(f"Row {index + 1} has invalid transaction details.")
            fingerprint = row["fingerprint"]
            if Transaction.query.filter_by(user_id=current_user.id, source_fingerprint=fingerprint).first():
                skipped += 1
                continue
            db.session.add(Transaction(
                user_id=current_user.id,
                type=row["type"],
                amount=amount,
                category_id=category_id or None,
                account_id=account_id or None,
                date=datetime.strptime(row["date"], "%Y-%m-%d").date(),
                payment_mode=row.get("payment_mode", "bank_transfer"),
                description=row["description"][:200] or None,
                source_fingerprint=fingerprint,
                source_account_number=row.get("account_number") or None,
            ))
            imported += 1
        db.session.delete(batch)
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        flash(str(error), "error")
        return render_template("transactions/import.html", rows=rows, batch=batch, categories=categories, accounts=accounts)
    except Exception:
        db.session.rollback()
        raise
    message = f"{imported} transaction(s) imported."
    if skipped:
        message += f" {skipped} duplicate(s) skipped."
    flash(message, "success")
    return redirect(url_for("transactions.index"))
