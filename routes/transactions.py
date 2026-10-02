from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
import re
import uuid

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from extensions import db
from finance import parse_month, shift_month, today, totals
from forms import TransactionForm, TransferForm
from bank_import import BankImportError as StatementImportError, parse_statement
from models import BankAccount, Category, ImportBatch, Transaction

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
    start_text = request.args.get("start", "").strip()
    end_text = request.args.get("end", "").strip()
    start_date = end_date = None
    if start_text or end_text:
        try:
            start_date = date.fromisoformat(start_text)
            end_date = date.fromisoformat(end_text)
            if (
                start_date > end_date
                or start_date < date(2000, 1, 1)
                or end_date > today() + timedelta(days=1)
            ):
                raise ValueError
        except ValueError:
            flash("Choose a valid date range from 1 January 2000 through tomorrow.", "error")
            start_date = end_date = None

    query = Transaction.query.filter_by(user_id=current_user.id).options(
        joinedload(Transaction.category),
        joinedload(Transaction.bank_account),
        joinedload(Transaction.transfer_to_account),
    )
    if start_date and end_date:
        query = query.filter(Transaction.date >= start_date, Transaction.date <= end_date)
        period_label = f"{start_date.strftime('%d %b %Y')} – {end_date.strftime('%d %b %Y')}"
    else:
        first = date(year, month, 1)
        next_year, next_month = shift_month(year, month, 1)
        query = query.filter(
            Transaction.date >= first,
            Transaction.date < date(next_year, next_month, 1),
        )
        period_label = date(year, month, 1).strftime("%B %Y")

    account_id = request.args.get("account", type=int)
    category_id = request.args.get("category", type=int)
    kind = request.args.get("kind", "")
    search = request.args.get("q", "").strip()[:100]
    if account_id and BankAccount.query.filter_by(
        id=account_id, user_id=current_user.id, is_active=True
    ).first():
        query = query.filter(
            (Transaction.account_id == account_id)
            | (Transaction.transfer_to_account_id == account_id)
        )
    else:
        account_id = None
    if category_id and Category.query.filter_by(id=category_id, user_id=current_user.id).first():
        query = query.filter(Transaction.category_id == category_id)
    else:
        category_id = None
    if kind in {"income", "expense", "transfer"}:
        query = query.filter(Transaction.type == kind)
    else:
        kind = ""
    if search:
        query = query.filter(Transaction.description.ilike(f"%{search}%"))
    items = query.order_by(Transaction.date.desc(), Transaction.id.desc()).all()

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
        month_label=period_label,
        month_key=f"{year}-{month:02d}",
        current_month=f"{now.year}-{now.month:02d}",
        prev_month=f"{prev_year}-{prev_month:02d}",
        next_month=None if is_current_month else f"{next_year}-{next_month:02d}",
        date_filtered=bool(start_date and end_date),
        filters={
            "start": start_text if start_date else "",
            "end": end_text if end_date else "",
            "account": account_id or "",
            "category": category_id or "",
            "kind": kind,
            "q": search,
        },
        accounts=BankAccount.query.filter_by(user_id=current_user.id, is_active=True).order_by(BankAccount.name).all(),
        categories=Category.query.filter_by(user_id=current_user.id).order_by(Category.name).all(),
    )


@transactions.route("/transfer", methods=["GET", "POST"])
@login_required
def transfer():
    form = TransferForm()
    accounts = BankAccount.query.filter_by(user_id=current_user.id, is_active=True).all()
    if form.validate_on_submit():
        account_ids = {account.id for account in accounts}
        if form.from_account_id.data not in account_ids or form.to_account_id.data not in account_ids:
            flash("Choose two of your active accounts.", "error")
        else:
            item = Transaction(
                user_id=current_user.id,
                type="transfer",
                amount=form.amount.data,
                account_id=form.from_account_id.data,
                transfer_to_account_id=form.to_account_id.data,
                date=form.date.data,
                payment_mode="bank_transfer",
                description=form.description.data or "Account transfer",
            )
            db.session.add(item)
            db.session.commit()
            flash("Transfer recorded. It is not counted as income or spending.", "success")
            return redirect(month_link(item.date))
    if request.method == "GET":
        form.date.data = today()
    return render_template("transactions/transfer.html", form=form, accounts=accounts, item=None)


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
    if item.type == "transfer":
        form = TransferForm()
        accounts = BankAccount.query.filter_by(
            user_id=current_user.id, is_active=True
        ).all()
        if request.method == "GET":
            form.amount.data = item.amount
            form.from_account_id.data = item.account_id
            form.to_account_id.data = item.transfer_to_account_id
            form.date.data = item.date
            form.description.data = item.description
        if form.validate_on_submit():
            account_ids = {account.id for account in accounts}
            if form.from_account_id.data not in account_ids or form.to_account_id.data not in account_ids:
                flash("Choose two of your active accounts.", "error")
            else:
                item.amount = form.amount.data
                item.account_id = form.from_account_id.data
                item.transfer_to_account_id = form.to_account_id.data
                item.date = form.date.data
                item.description = form.description.data or "Account transfer"
                db.session.commit()
                flash("Transfer updated.", "success")
                return redirect(month_link(item.date))
        return render_template(
            "transactions/transfer.html", form=form, accounts=accounts, item=item
        )
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


def _description_key(value):
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def _find_reconciliation_match(row):
    row_date = date.fromisoformat(row["date"])
    description = _description_key(row.get("description"))
    candidates = Transaction.query.filter(
        Transaction.user_id == current_user.id,
        Transaction.type == row["type"],
        Transaction.amount == Decimal(row["amount"]),
        Transaction.date >= row_date - timedelta(days=3),
        Transaction.date <= row_date + timedelta(days=3),
    ).all()
    ranked = []
    for candidate in candidates:
        candidate_description = _description_key(candidate.description)
        similarity = SequenceMatcher(None, description, candidate_description).ratio()
        if (
            description
            and candidate_description
            and (
                description == candidate_description
                or (min(len(description), len(candidate_description)) >= 6 and similarity >= 0.62)
            )
        ) or (
            not description and candidate.date == row_date
        ):
            ranked.append((similarity, abs((candidate.date - row_date).days), candidate))
    if not ranked:
        return None
    ranked.sort(key=lambda entry: (-entry[0], entry[1], entry[2].id))
    score, _, candidate = ranked[0]
    return {
        "id": candidate.id,
        "description": candidate.description or "No description",
        "date": candidate.date.isoformat(),
        "reconciled": candidate.reconciled,
        "confidence": round(score * 100),
    }


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

    existing = {
        fingerprint for (fingerprint,) in Transaction.query.filter_by(user_id=current_user.id)
        .with_entities(Transaction.source_fingerprint).all() if fingerprint
    }
    seen_fingerprints = set()
    for row in rows:
        row["match"] = _find_reconciliation_match(row)
        row["duplicate"] = (
            row["fingerprint"] in existing
            or row["fingerprint"] in seen_fingerprints
            or row["match"] is not None
        )
        seen_fingerprints.add(row["fingerprint"])
    batch = ImportBatch(id=uuid.uuid4().hex, user_id=current_user.id)
    batch.set_rows(rows)
    db.session.add(batch)
    db.session.commit()
    return render_template("transactions/import.html", rows=rows, batch=batch, categories=categories, accounts=accounts)


@transactions.route("/import/<batch_id>/commit", methods=["POST"])
@login_required
def commit_import(batch_id):
    batch = ImportBatch.query.filter_by(id=batch_id, user_id=current_user.id).first_or_404()
    rows = batch.get_rows()
    categories, accounts = _import_context()
    categories_by_id = {category.id: category for category in categories}
    category_ids = set(categories_by_id)
    account_ids = {a.id for a in accounts}
    selected = set(request.form.getlist("selected"))
    reconcile_selected = set(request.form.getlist("reconcile"))
    imported = 0
    skipped = 0
    reconciled = 0
    try:
        for index, row in enumerate(rows):
            if str(index) in reconcile_selected:
                matched = row.get("match")
                transaction = Transaction.query.filter_by(
                    id=matched["id"] if matched else None,
                    user_id=current_user.id,
                ).first()
                if not transaction or transaction.type == "transfer":
                    raise ValueError(f"Row {index + 1} no longer has a valid match to reconcile.")
                transaction.reconciled = True
                reconciled += 1
                continue
            if str(index) not in selected:
                continue
            try:
                amount = Decimal(row["amount"])
                category_id = int(request.form.get(f"category_{index}", "0") or 0)
                account_id = int(request.form.get(f"account_{index}", "0") or 0)
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError(f"Row {index + 1} has an invalid amount, category, or account.")
            if (
                amount <= 0
                or (category_id and category_id not in category_ids)
                or (category_id and categories_by_id[category_id].type != row["type"])
                or (account_id and account_id not in account_ids)
            ):
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
    if reconciled:
        message += f" {reconciled} existing transaction(s) reconciled."
    flash(message, "success")
    return redirect(url_for("transactions.index"))


@transactions.route("/import/<batch_id>/discard", methods=["POST"])
@login_required
def discard_import(batch_id):
    batch = ImportBatch.query.filter_by(id=batch_id, user_id=current_user.id).first_or_404()
    db.session.delete(batch)
    db.session.commit()
    flash("Statement preview discarded. The original file was not stored.", "info")
    return redirect(url_for("transactions.import_statement"))
