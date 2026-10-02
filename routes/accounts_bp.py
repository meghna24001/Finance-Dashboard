"""
FinSight — Bank Account management.
Named accounts_bp to avoid clashing with the existing account.py (profile).
"""
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from extensions import db
from forms import BankAccountForm
from models import BankAccount, ACCOUNT_COLORS, Transaction

accounts_bp = Blueprint("bank_accounts", __name__, url_prefix="/accounts")


def own_account_or_404(account_id):
    return BankAccount.query.filter_by(id=account_id, user_id=current_user.id).first_or_404()


@accounts_bp.route("")
@login_required
def index():
    accounts = BankAccount.query.filter_by(user_id=current_user.id).order_by(BankAccount.name).all()
    form = BankAccountForm()
    return render_template("bank_accounts/index.html", accounts=accounts, form=form, colors=ACCOUNT_COLORS)


@accounts_bp.route("/new", methods=["POST"])
@login_required
def create():
    form = BankAccountForm()
    if form.validate_on_submit():
        acct = BankAccount(
            user_id=current_user.id,
            name=form.name.data.strip(),
            account_type=form.account_type.data,
            last4=form.last4.data.strip() if form.last4.data else None,
            color=form.color.data or ACCOUNT_COLORS[0],
            balance_hint=form.balance_hint.data,
        )
        db.session.add(acct)
        db.session.commit()
        flash("Account added.", "success")
    else:
        for field in form:
            for err in field.errors:
                flash(err, "error")
    return redirect(url_for("bank_accounts.index"))


@accounts_bp.route("/<int:account_id>/edit", methods=["GET", "POST"])
@login_required
def edit(account_id):
    acct = own_account_or_404(account_id)
    form = BankAccountForm(obj=acct)
    if form.validate_on_submit():
        acct.name = form.name.data.strip()
        acct.account_type = form.account_type.data
        acct.last4 = form.last4.data.strip() if form.last4.data else None
        acct.color = form.color.data or acct.color
        acct.balance_hint = form.balance_hint.data
        db.session.commit()
        flash("Account updated.", "success")
        return redirect(url_for("bank_accounts.index"))
    return render_template("bank_accounts/edit.html", form=form, acct=acct, colors=ACCOUNT_COLORS)


@accounts_bp.route("/<int:account_id>/delete", methods=["POST"])
@login_required
def delete(account_id):
    acct = own_account_or_404(account_id)
    # Preserve historical entries while detaching both sides of any transfer.
    for txn in acct.transactions:
        txn.account_id = None
    for txn in Transaction.query.filter_by(
        user_id=current_user.id, transfer_to_account_id=acct.id
    ).all():
        txn.transfer_to_account_id = None
    db.session.delete(acct)
    db.session.commit()
    flash("Account removed. Transactions are unaffected.", "success")
    return redirect(url_for("bank_accounts.index"))
