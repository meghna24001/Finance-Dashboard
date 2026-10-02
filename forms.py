from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    DecimalField,
    HiddenField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, Optional, ValidationError

from currency_utils import get_countries
from models import ACCOUNT_COLORS, ACCOUNT_TYPES, FREQUENCIES, PAYMENT_MODES, BankAccount, Budget, User


def clean_email(value):
    """Emails are stored in lowercase without spaces, so 'Meg@X.com ' and 'meg@x.com' match."""
    return value.strip().lower() if value else value


class RegisterForm(FlaskForm):
    name = StringField(
        "Name",
        validators=[DataRequired(message="Enter your name."), Length(max=80)],
    )
    email = StringField(
        "Email",
        filters=[clean_email],
        validators=[
            DataRequired(message="Enter your email address."),
            Email(message="Enter a valid email address."),
            Length(max=120),
        ],
    )
    country = SelectField("Country", validators=[DataRequired(message="Choose your country.")])
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(message="Create a password."),
            Length(min=8, max=128, message="Use 8 to 128 characters."),
        ],
    )
    confirm_password = PasswordField(
        "Confirm password",
        validators=[
            DataRequired(message="Type your password again."),
            EqualTo("password", message="Passwords don't match."),
        ],
    )
    submit = SubmitField("Create account")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.country.choices = [("", "Select your country")] + get_countries()

    def validate_email(self, field):
        if User.query.filter_by(email=field.data).first():
            raise ValidationError("An account with this email already exists. Sign in instead.")


class LoginForm(FlaskForm):
    email = StringField(
        "Email",
        filters=[clean_email],
        validators=[DataRequired(message="Enter your email address.")],
    )
    password = PasswordField("Password", validators=[DataRequired(message="Enter your password.")])
    remember = BooleanField("Keep me signed in on this device")
    submit = SubmitField("Sign in")


class ForgotPasswordForm(FlaskForm):
    email = StringField(
        "Email",
        filters=[clean_email],
        validators=[
            DataRequired(message="Enter your email address."),
            Email(message="Enter a valid email address."),
        ],
    )
    submit = SubmitField("Send reset instructions")


class ResetPasswordForm(FlaskForm):
    new_password = PasswordField(
        "New password",
        validators=[
            DataRequired(message="Create a new password."),
            Length(min=8, max=128, message="Use 8 to 128 characters."),
        ],
    )
    confirm_new_password = PasswordField(
        "Confirm new password",
        validators=[
            DataRequired(message="Type your password again."),
            EqualTo("new_password", message="Passwords don't match."),
        ],
    )
    submit = SubmitField("Reset password")


class ProfileForm(FlaskForm):
    name = StringField(
        "Name",
        validators=[DataRequired(message="Enter your name."), Length(max=80)],
    )
    country = SelectField("Country", validators=[DataRequired(message="Choose your country.")])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.country.choices = get_countries()


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField(
        "Current password",
        validators=[DataRequired(message="Enter your current password.")],
    )
    new_password = PasswordField(
        "New password",
        validators=[
            DataRequired(message="Create a new password."),
            Length(min=8, max=128, message="Use 8 to 128 characters."),
        ],
    )
    confirm_new_password = PasswordField(
        "Confirm new password",
        validators=[
            DataRequired(message="Type your new password again."),
            EqualTo("new_password", message="Passwords don't match."),
        ],
    )

    def validate_current_password(self, field):
        if not current_user.check_password(field.data):
            raise ValidationError("That isn't your current password.")

    def validate_new_password(self, field):
        if current_user.check_password(field.data):
            raise ValidationError("Choose a password different from your current one.")


# ---------------------------------------------------------------- categories

def collapse_spaces(value):
    return " ".join(value.split()) if value else value


def category_name_taken(name, kind, exclude_id=None):
    wanted = name.casefold()
    return any(
        c.type == kind and c.id != exclude_id and c.name.casefold() == wanted
        for c in current_user.categories
    )


class NewCategoryForm(FlaskForm):
    name = StringField(
        "Name",
        filters=[collapse_spaces],
        validators=[
            DataRequired(message="Enter a category name."),
            Length(max=40, message="Use 40 characters or fewer."),
        ],
    )
    kind = SelectField("Type", choices=[("expense", "Expense"), ("income", "Income")])

    def validate_name(self, field):
        if category_name_taken(field.data, self.kind.data):
            raise ValidationError("You already have a category with this name.")


class RenameCategoryForm(FlaskForm):
    name = StringField(
        "Name",
        filters=[collapse_spaces],
        validators=[
            DataRequired(message="Enter a category name."),
            Length(max=40, message="Use 40 characters or fewer."),
        ],
    )

    def __init__(self, *args, category, **kwargs):
        super().__init__(*args, **kwargs)
        self.category = category

    def validate_name(self, field):
        if category_name_taken(field.data, self.category.type, exclude_id=self.category.id):
            raise ValidationError("You already have a category with this name.")


# -------------------------------------------------------------- transactions

MAX_AMOUNT = Decimal("99999999.99")


class AmountField(DecimalField):
    """A money amount with friendly error messages."""

    def process_formdata(self, valuelist):
        if not valuelist or not valuelist[0].strip():
            self.data = None
            return
        try:
            super().process_formdata([valuelist[0].strip()])
            if self.data is not None and not self.data.is_finite():
                raise ValueError
        except ValueError:
            self.data = None
            raise ValueError("Enter an amount like 250 or 250.50.")


class SimpleDateField(DateField):
    """A date with friendly error messages."""

    def process_formdata(self, valuelist):
        if not valuelist or not valuelist[0].strip():
            self.data = None
            return
        try:
            super().process_formdata(valuelist)
        except ValueError:
            self.data = None
            raise ValueError("Enter a valid date.")


class CategoryField(SelectField):
    """A dropdown of the person's own categories (numbers underneath, names on screen)."""

    def process_formdata(self, valuelist):
        try:
            super().process_formdata(valuelist)
        except ValueError:
            self.data = None
            raise ValueError("Choose a category.")

    def pre_validate(self, form):
        if self.process_errors:
            return
        if self.data is None or self.data not in [value for value, _ in self.choices]:
            raise ValidationError("Choose a category.")


def validate_money(field):
    if field.data is None:
        if not field.process_errors:
            raise ValidationError("Enter an amount.")
        return
    if field.data <= 0:
        raise ValidationError("Enter an amount greater than zero.")
    if field.data > MAX_AMOUNT:
        raise ValidationError("That amount is too large.")
    if field.data != field.data.quantize(Decimal("0.01")):
        raise ValidationError("Use at most 2 decimal places.")


class OptionalAccountField(SelectField):
    """A bank account dropdown that safely defaults to 0 when omitted or empty."""
    def process_formdata(self, valuelist):
        if not valuelist or not valuelist[0]:
            self.data = 0
            return
        try:
            self.data = int(valuelist[0])
        except (ValueError, TypeError):
            self.data = 0

    def pre_validate(self, form):
        pass


class PaymentModeField(SelectField):
    """A payment mode dropdown that defaults to cash when omitted or invalid."""
    def process_formdata(self, valuelist):
        if not valuelist or not valuelist[0]:
            self.data = "cash"
            return
        super().process_formdata(valuelist)

    def pre_validate(self, form):
        if self.data and self.data not in [v for v, _ in self.choices]:
            self.data = "cash"


class TransactionForm(FlaskForm):
    amount = AmountField("Amount", places=2)
    category_id = CategoryField("Category", coerce=int)
    date = SimpleDateField("Date")
    payment_mode = PaymentModeField("Payment Mode", choices=PAYMENT_MODES, default="cash")
    upi_id = StringField(
        "UPI ID (optional)",
        filters=[lambda v: v.strip() if v else v],
        validators=[Length(max=80, message="Use 80 characters or fewer.")],
    )
    account_id = OptionalAccountField("Bank Account / Wallet (optional)", coerce=int, default=0)
    source_account_number = StringField(
        "Statement account number (optional)",
        filters=[lambda v: v.strip() if v else v],
        validators=[Length(max=40, message="Use 40 characters or fewer.")],
    )
    receipt_path = HiddenField("Receipt Path")
    description = StringField(
        "Note (optional)",
        filters=[lambda v: v.strip() if v else v],
        validators=[Length(max=200, message="Use 200 characters or fewer.")],
    )

    def __init__(self, *args, kind, **kwargs):
        super().__init__(*args, **kwargs)
        # Categories of the right kind
        own = sorted(
            (c for c in current_user.categories if c.type == kind),
            key=lambda c: c.name.casefold(),
        )
        self.category_id.choices = [(c.id, c.name) for c in own]

        # Bank accounts
        user_accounts = BankAccount.query.filter_by(user_id=current_user.id, is_active=True).all()
        self.account_id.choices = [(0, "None / Default")] + [(a.id, f"{a.name} ({a.account_type.capitalize()})") for a in user_accounts]

    def validate_amount(self, field):
        validate_money(field)

    def validate_date(self, field):
        if field.data is None:
            if not field.process_errors:
                raise ValidationError("Choose a date.")
            return
        latest = datetime.now(timezone.utc).date() + timedelta(days=1)
        if field.data > latest:
            raise ValidationError("Choose a date that isn't in the future.")
        if field.data < date(2000, 1, 1):
            raise ValidationError("Choose a date from the year 2000 onwards.")


class TransferForm(FlaskForm):
    amount = AmountField("Amount", places=2)
    from_account_id = SelectField("From account", coerce=int, validators=[NumberRange(min=1)])
    to_account_id = SelectField("To account", coerce=int, validators=[NumberRange(min=1)])
    date = SimpleDateField("Date")
    description = StringField(
        "Note (optional)",
        filters=[lambda value: value.strip() if value else value],
        validators=[Length(max=200, message="Use 200 characters or fewer.")],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        accounts = BankAccount.query.filter_by(
            user_id=current_user.id, is_active=True
        ).order_by(BankAccount.name).all()
        choices = [(account.id, account.name) for account in accounts]
        self.from_account_id.choices = choices
        self.to_account_id.choices = choices

    def validate_amount(self, field):
        validate_money(field)

    def validate_date(self, field):
        if field.data is None:
            if not field.process_errors:
                raise ValidationError("Choose a date.")
            return
        latest = datetime.now(timezone.utc).date() + timedelta(days=1)
        if field.data > latest or field.data < date(2000, 1, 1):
            raise ValidationError("Choose a valid date from the year 2000 onwards.")

    def validate_to_account_id(self, field):
        if field.data and field.data == self.from_account_id.data:
            raise ValidationError("Choose two different accounts.")


# ------------------------------------------------------------------- Bank Accounts

class BankAccountForm(FlaskForm):
    name = StringField(
        "Account / Bank Name",
        validators=[DataRequired(message="Enter the account or bank name."), Length(max=80)],
    )
    account_type = SelectField("Account Type", choices=ACCOUNT_TYPES, default="savings")
    last4 = StringField(
        "Last 4 Digits (optional)",
        validators=[Optional(), Length(min=4, max=4, message="Must be exactly 4 digits.")],
    )
    color = SelectField(
        "Color Tag",
        choices=[(c, c) for c in ACCOUNT_COLORS],
        default=ACCOUNT_COLORS[0],
    )
    balance_hint = AmountField("Current Balance (optional)", places=2, validators=[Optional()])
    submit = SubmitField("Save Account")


# ------------------------------------------------------------------- Recurring / SIP

class RecurringForm(FlaskForm):
    name = StringField(
        "Name / Label (e.g. 'Nifty 50 Index Fund SIP', 'House Rent')",
        validators=[DataRequired(message="Enter a name."), Length(max=100)],
    )
    amount = AmountField("Amount", places=2)
    kind = SelectField("Type", choices=[("expense", "Expense / Investment"), ("income", "Income / Salary")], default="expense")
    frequency = SelectField("Frequency", choices=FREQUENCIES, default="monthly")
    day_of_month = IntegerField(
        "Day of Month (1–28)",
        validators=[Optional(), NumberRange(min=1, max=28, message="Choose a day between 1 and 28.")],
    )
    start_date = SimpleDateField("Start Date / First Due", default=date.today)
    payment_mode = SelectField("Payment Mode", choices=PAYMENT_MODES, default="bank_transfer")
    category_id = SelectField("Category (optional)", coerce=int)
    account_id = SelectField("Linked Account (optional)", coerce=int)
    notes = StringField("Notes (optional)", validators=[Length(max=200)])
    submit = SubmitField("Save Recurring Transaction")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cats = sorted(current_user.categories, key=lambda c: (c.type, c.name.casefold()))
        self.category_id.choices = [(0, "None")] + [(c.id, f"{c.name} ({c.type})") for c in cats]

        accts = BankAccount.query.filter_by(user_id=current_user.id, is_active=True).all()
        self.account_id.choices = [(0, "None")] + [(a.id, a.name) for a in accts]

    def validate_amount(self, field):
        validate_money(field)


# ------------------------------------------------------------------- budgets

class NewBudgetForm(FlaskForm):
    category_id = CategoryField("Category", coerce=int)
    amount = AmountField("Monthly limit", places=2)

    def __init__(self, *args, month=None, **kwargs):
        super().__init__(*args, **kwargs)
        budgeted = {
            budget.category_id
            for budget in Budget.query.filter_by(user_id=current_user.id, month=month).all()
        } if month else set()
        free = sorted(
            (c for c in current_user.categories if c.type == "expense" and c.id not in budgeted),
            key=lambda c: c.name.casefold(),
        )
        self.category_id.choices = [(c.id, c.name) for c in free]

    def validate_amount(self, field):
        validate_money(field)


class EditBudgetForm(FlaskForm):
    amount = AmountField("Monthly limit", places=2)

    def validate_amount(self, field):
        validate_money(field)
