from datetime import datetime, timezone, timedelta

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError

from extensions import db, limiter
from forms import ForgotPasswordForm, LoginForm, RegisterForm, ResetPasswordForm
from models import PasswordResetToken, User, add_default_categories

# A Blueprint is a group of related pages. This one holds register, login, logout, and password recovery.
auth = Blueprint("auth", __name__)


def is_safe_next(target):
    """Only allow redirects to pages on our own site, never to another website."""
    return (
        bool(target)
        and target.startswith("/")
        and not target.startswith("//")
        and "\\" not in target
    )


@auth.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute;30 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    form = RegisterForm()
    if form.validate_on_submit():
        user = User(email=form.email.data, name=form.name.data.strip())
        user.set_password(form.password.data)
        user.set_country(form.country.data)  # also sets the currency
        add_default_categories(user)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            # Someone registered the same email a split second earlier.
            db.session.rollback()
            form.email.errors.append("An account with this email already exists. Sign in instead.")
            return render_template("auth/register.html", form=form)

        login_user(user)
        flash("Your account is ready. Welcome to FinSight!", "success")
        return redirect(url_for("dashboard.home"))

    return render_template("auth/register.html", form=form)


@auth.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute;60 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            next_page = request.args.get("next")
            return redirect(next_page if is_safe_next(next_page) else url_for("dashboard.home"))
        flash("Email or password is incorrect.", "error")

    return render_template("auth/login.html", form=form)


@auth.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per minute;20 per hour", methods=["POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            # Invalidate any existing unused tokens for this user
            PasswordResetToken.query.filter_by(user_id=user.id, used=False).update({"used": True})
            db.session.commit()

            # Create a new token
            token = PasswordResetToken(user_id=user.id)
            db.session.add(token)
            db.session.commit()

            reset_url = url_for("auth.reset_password", token=token.token, _external=True)
            current_app.logger.info("Password reset requested for %s. Reset link: %s", user.email, reset_url)
            # In development/local mode, flash the direct link so it's directly accessible
            flash(f"Password reset link generated! Click here to reset: {reset_url}", "info")
            return redirect(url_for("auth.login"))

        # Neutral message to prevent account enumeration
        flash("If that email is registered, we've prepared your reset instructions.", "info")
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html", form=form)


@auth.route("/reset-password/<token>", methods=["GET", "POST"])
@limiter.limit("5 per minute;20 per hour", methods=["POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    reset_token = PasswordResetToken.query.filter_by(token=token).first()
    if not reset_token or not reset_token.is_valid:
        flash("This password reset link is invalid or has expired.", "error")
        return redirect(url_for("auth.forgot_password"))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user = db.session.get(User, reset_token.user_id)
        if user:
            user.set_password(form.new_password.data)
            reset_token.used = True
            db.session.commit()
            flash("Your password has been reset successfully. Please sign in.", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", form=form, token=token)


@auth.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You're signed out.", "info")
    return redirect(url_for("auth.login"))
