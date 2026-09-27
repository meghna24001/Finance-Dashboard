from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from currency_utils import format_money
from extensions import db, limiter
from forms import ChangePasswordForm, ProfileForm

# The signed-in person's own profile: their details and their password.
# (Named "account", not "profile", because Python already has a built-in module called profile.)
account = Blueprint("account", __name__)


def show_profile(details_form, password_form):
    sample = format_money(100000, current_user.currency, current_user.country)
    return render_template(
        "profile.html", details_form=details_form, password_form=password_form, sample=sample
    )


@account.route("/profile")
@login_required
def show():
    # obj=current_user fills the form with what is saved today.
    return show_profile(ProfileForm(obj=current_user), ChangePasswordForm())


@account.route("/profile/details", methods=["POST"])
@login_required
def update_details():
    form = ProfileForm()
    if form.validate_on_submit():
        old_currency = current_user.currency
        current_user.name = form.name.data.strip()
        current_user.set_country(form.country.data)  # also updates the currency
        db.session.commit()

        if current_user.currency != old_currency:
            flash(
                f"Profile updated. Amounts now show in {current_user.currency}. "
                "Existing amounts are not converted.",
                "success",
            )
        else:
            flash("Profile updated.", "success")
        return redirect(url_for("account.show"))

    return show_profile(form, ChangePasswordForm())


@account.route("/profile/password", methods=["POST"])
@login_required
@limiter.limit("5 per minute;20 per hour")
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        current_user.set_password(form.new_password.data)
        db.session.commit()
        flash("Password updated.", "success")
        return redirect(url_for("account.show"))

    return show_profile(ProfileForm(obj=current_user), form)

