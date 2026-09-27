from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
from forms import NewCategoryForm, RenameCategoryForm
from models import Category, Transaction

categories = Blueprint("categories", __name__, url_prefix="/categories")


def own_category_or_404(category_id):
    return Category.query.filter_by(id=category_id, user_id=current_user.id).first_or_404()


def uses_of(category):
    """How many transactions use this category."""
    return Transaction.query.filter_by(category_id=category.id, user_id=current_user.id).count()


def show_index(form):
    counts = dict(
        db.session.query(Transaction.category_id, func.count(Transaction.id))
        .filter(Transaction.user_id == current_user.id)
        .group_by(Transaction.category_id)
        .all()
    )
    ordered = sorted(current_user.categories, key=lambda c: c.name.casefold())
    return render_template(
        "categories/index.html",
        form=form,
        expense_categories=[c for c in ordered if c.type == "expense"],
        income_categories=[c for c in ordered if c.type == "income"],
        counts=counts,
    )


@categories.route("")
@login_required
def index():
    return show_index(NewCategoryForm())


@categories.route("/new", methods=["POST"])
@login_required
def create():
    form = NewCategoryForm()
    if form.validate_on_submit():
        db.session.add(Category(name=form.name.data, type=form.kind.data, user_id=current_user.id))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            form.name.errors.append("You already have a category with this name.")
            return show_index(form)
        flash("Category added.", "success")
        return redirect(url_for("categories.index"))
    return show_index(form)


@categories.route("/<int:category_id>/edit", methods=["GET", "POST"])
@login_required
def edit(category_id):
    category = own_category_or_404(category_id)
    form = RenameCategoryForm(category=category, obj=category)

    if form.validate_on_submit():
        category.name = form.name.data
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            form.name.errors.append("You already have a category with this name.")
            return render_template("categories/edit.html", form=form, category=category, uses=uses_of(category))
        flash("Category renamed.", "success")
        return redirect(url_for("categories.index"))

    return render_template("categories/edit.html", form=form, category=category, uses=uses_of(category))


@categories.route("/<int:category_id>/delete", methods=["POST"])
@login_required
def delete(category_id):
    category = own_category_or_404(category_id)
    uses = uses_of(category)
    if uses:
        flash(
            f"“{category.name}” is used by {uses} transaction{'s' if uses != 1 else ''}, so it can't be deleted. "
            "Rename it, or change or delete those transactions first.",
            "error",
        )
        return redirect(url_for("categories.edit", category_id=category.id))

    db.session.delete(category)
    db.session.commit()
    flash("Category deleted.", "success")
    return redirect(url_for("categories.index"))
