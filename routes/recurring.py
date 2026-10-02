"""
FinSight — Recurring / SIP transaction management.
"""
import calendar
from datetime import date, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from extensions import db
from forms import RecurringForm
from models import RecurringTransaction, Transaction

recurring_bp = Blueprint("recurring", __name__, url_prefix="/recurring")

FREQ_LABELS = {
    "daily": "Daily",
    "weekly": "Weekly",
    "monthly": "Monthly",
    "quarterly": "Every 3 Months",
    "yearly": "Yearly",
}


def own_recurring_or_404(rec_id):
    return RecurringTransaction.query.filter_by(id=rec_id, user_id=current_user.id).first_or_404()


def add_months(sourcedate, months):
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def next_due_after(current_due: date, frequency: str) -> date:
    """Advance the due date by one frequency period."""
    if frequency == "daily":
        return current_due + timedelta(days=1)
    elif frequency == "weekly":
        return current_due + timedelta(weeks=1)
    elif frequency == "monthly":
        return add_months(current_due, 1)
    elif frequency == "quarterly":
        return add_months(current_due, 3)
    elif frequency == "yearly":
        return add_months(current_due, 12)
    return add_months(current_due, 1)


@recurring_bp.route("")
@login_required
def index():
    today_date = date.today()
    rules = RecurringTransaction.query.filter_by(user_id=current_user.id).order_by(
        RecurringTransaction.next_due
    ).all()
    form = RecurringForm()
    return render_template(
        "recurring/index.html",
        rules=rules,
        form=form,
        freq_labels=FREQ_LABELS,
        today=today_date,
        reminder_cutoff=today_date + timedelta(days=7),
    )


@recurring_bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    form = RecurringForm()
    if form.validate_on_submit():
        rule = RecurringTransaction(
            user_id=current_user.id,
            name=form.name.data.strip(),
            amount=form.amount.data,
            type=form.kind.data,
            frequency=form.frequency.data,
            day_of_month=form.day_of_month.data,
            next_due=form.start_date.data,
            payment_mode=form.payment_mode.data,
            notes=form.notes.data or None,
            category_id=form.category_id.data if form.category_id.data else None,
            account_id=form.account_id.data if form.account_id.data else None,
        )
        db.session.add(rule)
        db.session.commit()
        flash("Recurring transaction saved.", "success")
        return redirect(url_for("recurring.index"))
    return render_template("recurring/form.html", form=form, rule=None)


@recurring_bp.route("/<int:rec_id>/edit", methods=["GET", "POST"])
@login_required
def edit(rec_id):
    rule = own_recurring_or_404(rec_id)
    form = RecurringForm(obj=rule)
    if form.validate_on_submit():
        rule.name = form.name.data.strip()
        rule.amount = form.amount.data
        rule.type = form.kind.data
        rule.frequency = form.frequency.data
        rule.day_of_month = form.day_of_month.data
        rule.next_due = form.start_date.data
        rule.payment_mode = form.payment_mode.data
        rule.notes = form.notes.data or None
        rule.category_id = form.category_id.data if form.category_id.data else None
        rule.account_id = form.account_id.data if form.account_id.data else None
        db.session.commit()
        flash("Updated.", "success")
        return redirect(url_for("recurring.index"))
    # Pre-fill start_date from next_due
    if request.method == "GET":
        form.start_date.data = rule.next_due
        form.kind.data = rule.type
    return render_template("recurring/form.html", form=form, rule=rule)


@recurring_bp.route("/<int:rec_id>/toggle", methods=["POST"])
@login_required
def toggle(rec_id):
    rule = own_recurring_or_404(rec_id)
    rule.is_active = not rule.is_active
    db.session.commit()
    flash("Recurring transaction " + ("activated" if rule.is_active else "paused") + ".", "success")
    return redirect(url_for("recurring.index"))


@recurring_bp.route("/<int:rec_id>/delete", methods=["POST"])
@login_required
def delete(rec_id):
    rule = own_recurring_or_404(rec_id)
    db.session.delete(rule)
    db.session.commit()
    flash("Recurring transaction deleted.", "success")
    return redirect(url_for("recurring.index"))


@recurring_bp.route("/run", methods=["POST"])
@login_required
def run_due():
    """Manually trigger processing of due recurring transactions for the current user."""
    today = date.today()
    due_rules = RecurringTransaction.query.filter(
        RecurringTransaction.user_id == current_user.id,
        RecurringTransaction.is_active == True,
        RecurringTransaction.next_due <= today,
    ).all()

    created = 0
    already_generated = 0
    for rule in due_rules:
        if Transaction.query.filter_by(
            recurring_id=rule.id,
            recurring_due_date=rule.next_due,
        ).first():
            rule.next_due = next_due_after(rule.next_due, rule.frequency)
            already_generated += 1
            continue
        txn = Transaction(
            user_id=current_user.id,
            type=rule.type,
            amount=rule.amount,
            category_id=rule.category_id,
            account_id=rule.account_id,
            payment_mode=rule.payment_mode,
            description=rule.name,
            date=rule.next_due,
            recurring_id=rule.id,
            recurring_due_date=rule.next_due,
        )
        db.session.add(txn)
        rule.next_due = next_due_after(rule.next_due, rule.frequency)
        created += 1

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("A scheduled item was processed at the same time by another request. Please refresh and try again.", "error")
        return redirect(url_for("recurring.index"))
    if created:
        flash(f"{created} recurring transaction{'s' if created > 1 else ''} added.", "success")
    elif already_generated:
        flash("Already-generated scheduled items were skipped.", "info")
    else:
        flash("No transactions due right now.", "info")
    return redirect(url_for("recurring.index"))
