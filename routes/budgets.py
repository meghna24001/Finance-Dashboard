from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from extensions import db
from finance import budget_rows, budget_summary, month_transactions, parse_month, shift_month, today
from forms import EditBudgetForm, NewBudgetForm
from models import Budget

budgets = Blueprint("budgets", __name__, url_prefix="/budgets")


def own_budget_or_404(budget_id):
    return Budget.query.filter_by(id=budget_id, user_id=current_user.id).first_or_404()


def month_key():
    """The month in the address (?month=2026-09), cleaned up. Bad values become this month."""
    year, month = parse_month(request.args.get("month"))
    return f"{year}-{month:02d}"


def show_index(form):
    year, month = parse_month(request.args.get("month"))
    month_start = date(year, month, 1)
    items = month_transactions(current_user.id, year, month)
    budgets_for_month = Budget.query.filter_by(user_id=current_user.id, month=month_start).all()
    rows = budget_rows(budgets_for_month, items)

    now = today()
    prev_year, prev_month = shift_month(year, month, -1)
    next_year, next_month = shift_month(year, month, 1)
    is_current_month = (year, month) == (now.year, now.month)

    return render_template(
        "budgets/index.html",
        form=form,
        rows=rows,
        summary=budget_summary(rows, items, budgets_for_month),
        can_add=bool(form.category_id.choices),
        month_label=date(year, month, 1).strftime("%B %Y"),
        month_key=f"{year}-{month:02d}",
        current_month=f"{now.year}-{now.month:02d}",
        prev_month=f"{prev_year}-{prev_month:02d}",
        next_month=None if is_current_month else f"{next_year}-{next_month:02d}",
    )


@budgets.route("")
@login_required
def index():
    year, month = parse_month(request.args.get("month"))
    return show_index(NewBudgetForm(month=date(year, month, 1)))


@budgets.route("/new", methods=["POST"])
@login_required
def create():
    year, month = parse_month(request.args.get("month"))
    selected_month = date(year, month, 1)
    form = NewBudgetForm(month=selected_month)
    if form.validate_on_submit():
        db.session.add(
            Budget(
                user_id=current_user.id,
                category_id=form.category_id.data,
                amount=form.amount.data,
                month=selected_month,
            )
        )
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            form.category_id.errors.append("This category already has a budget.")
            return show_index(form)
        flash("Budget added.", "success")
        return redirect(url_for("budgets.index", month=month_key()))
    return show_index(form)


@budgets.route("/<int:budget_id>/edit", methods=["GET", "POST"])
@login_required
def edit(budget_id):
    budget = own_budget_or_404(budget_id)
    form = EditBudgetForm(obj=budget)

    if form.validate_on_submit():
        budget.amount = form.amount.data
        db.session.commit()
        flash("Budget updated.", "success")
        return redirect(url_for("budgets.index", month=month_key()))

    return render_template("budgets/edit.html", form=form, budget=budget, month_key=month_key())


@budgets.route("/<int:budget_id>/delete", methods=["POST"])
@login_required
def delete(budget_id):
    budget = own_budget_or_404(budget_id)
    db.session.delete(budget)
    db.session.commit()
    flash("Budget removed. Your transactions are untouched.", "success")
    return redirect(url_for("budgets.index", month=month_key()))
