import secrets
import json
from datetime import date, datetime, timezone, timedelta

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from currency_utils import currency_for_country
from extensions import db, login_manager


class User(UserMixin, db.Model):
    """One row per person who signs up."""

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)  # never the real password
    name = db.Column(db.String(80), nullable=False)
    country = db.Column(db.String(2), default="IN", nullable=False)  # e.g. "IN", "US"
    currency = db.Column(db.String(3), default="INR", nullable=False)
    theme = db.Column(db.String(10), default="auto", nullable=False)  # "light", "dark", "auto"
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    categories = db.relationship("Category", backref="user", cascade="all, delete-orphan")
    transactions = db.relationship("Transaction", backref="user", cascade="all, delete-orphan")
    budgets = db.relationship("Budget", backref="user", cascade="all, delete-orphan")
    bank_accounts = db.relationship("BankAccount", backref="user", cascade="all, delete-orphan")
    recurring_transactions = db.relationship("RecurringTransaction", backref="user", cascade="all, delete-orphan")
    reset_tokens = db.relationship("PasswordResetToken", backref="user", cascade="all, delete-orphan")
    sync_receipts = db.relationship("SyncReceipt", backref="user", cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def initials(self):
        """Letters shown in the round profile picture, e.g. "Asha Rao" -> "AR"."""
        parts = self.name.split()
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][0].upper()
        return (parts[0][0] + parts[-1][0]).upper()

    def set_country(self, country_code):
        """Picking a country automatically sets the matching currency."""
        self.country = country_code
        self.currency = currency_for_country(country_code)

    def __repr__(self):
        return f"<User {self.email}>"


@login_manager.user_loader
def load_user(user_id):
    """Flask-Login calls this on every request to find who is logged in."""
    return db.session.get(User, int(user_id))


# ----------------------------------------------------------------- Bank Accounts

ACCOUNT_TYPES = [
    ("savings", "Savings Account"),
    ("current", "Current Account"),
    ("credit", "Credit Card"),
    ("wallet", "Digital Wallet / UPI"),
    ("cash", "Cash"),
]

ACCOUNT_COLORS = ["#6366f1", "#10b981", "#f59e0b", "#f43f5e", "#06b6d4", "#8b5cf6"]


class BankAccount(db.Model):
    """A bank account, wallet, or cash pocket owned by the user."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)  # e.g. "SBI Savings", "HDFC Credit"
    account_type = db.Column(db.String(20), nullable=False, default="savings")
    last4 = db.Column(db.String(4), nullable=True)   # last 4 digits (optional)
    color = db.Column(db.String(7), nullable=False, default="#6366f1")  # hex color
    balance_hint = db.Column(db.Numeric(12, 2), nullable=True)  # manually entered, not computed
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    transactions = db.relationship(
        "Transaction", backref="bank_account", foreign_keys="Transaction.account_id"
    )

    def __repr__(self):
        return f"<BankAccount {self.name}>"


# ----------------------------------------------------------------- Categories

DEFAULT_CATEGORIES = {
    "expense": ["Food", "Transport", "Rent", "Bills", "Shopping", "Health", "Entertainment", "Education", "Other"],
    "income": ["Salary", "Freelance", "Gift", "Other"],
}


class Category(db.Model):
    """Categories belong to a user, so everyone can have their own (Food, Rent, ...)."""

    __table_args__ = (
        db.UniqueConstraint("user_id", "type", "name", name="uq_category_user_type_name"),
        db.CheckConstraint("type IN ('income', 'expense')", name="ck_category_type"),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), nullable=False)
    type = db.Column(db.String(7), nullable=False)  # "income" or "expense"
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    transactions = db.relationship("Transaction", backref="category")
    budgets = db.relationship("Budget", backref="category", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Category {self.name}>"


# ----------------------------------------------------------------- Transactions

PAYMENT_MODES = [
    ("cash", "Cash"),
    ("card", "Card"),
    ("upi", "UPI"),
    ("bank_transfer", "Bank Transfer"),
    ("net_banking", "Net Banking"),
    ("cheque", "Cheque"),
]


class Transaction(db.Model):
    """One income, expense, or account-to-account transfer entry."""

    __table_args__ = (
        db.CheckConstraint("type IN ('income', 'expense', 'transfer')", name="ck_transaction_type"),
        db.CheckConstraint("amount > 0", name="ck_transaction_amount_positive"),
        db.Index("ix_transaction_user_date", "user_id", "date"),
        db.UniqueConstraint("user_id", "source_fingerprint", name="uq_transaction_user_source_fingerprint"),
        db.UniqueConstraint("recurring_id", "recurring_due_date", name="uq_transaction_recurring_due"),
    )

    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    type = db.Column(db.String(7), nullable=False)  # "income" or "expense"
    description = db.Column(db.String(200))
    date = db.Column(db.Date, default=date.today, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # New fields
    payment_mode = db.Column(db.String(20), default="cash", nullable=False)
    upi_id = db.Column(db.String(80), nullable=True)           # e.g. "user@paytm"
    account_id = db.Column(db.Integer, db.ForeignKey("bank_account.id"), nullable=True)
    transfer_to_account_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "bank_account.id",
            name="fk_transaction_transfer_to_account_id_bank_account",
        ),
        nullable=True,
    )
    receipt_path = db.Column(db.String(255), nullable=True)    # path to scanned receipt image
    recurring_id = db.Column(db.Integer, db.ForeignKey("recurring_transaction.id"), nullable=True)
    recurring_due_date = db.Column(db.Date, nullable=True)
    reconciled = db.Column(db.Boolean, default=False, nullable=False)
    transfer_to_account = db.relationship("BankAccount", foreign_keys=[transfer_to_account_id])

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"))
    source_fingerprint = db.Column(db.String(64), nullable=True)
    source_account_number = db.Column(db.String(40), nullable=True)

    def __repr__(self):
        return f"<Transaction {self.type} {self.amount}>"


class ImportBatch(db.Model):
    """Short-lived, user-owned parsed statement rows waiting for confirmation."""

    id = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    rows_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = db.relationship("User", backref=db.backref("import_batches", cascade="all, delete-orphan"))

    def set_rows(self, rows):
        self.rows_json = json.dumps(rows, separators=(",", ":"))

    def get_rows(self):
        return json.loads(self.rows_json)




# ----------------------------------------------------------------- Budgets

class Budget(db.Model):
    """A monthly spending limit for one expense category."""

    __table_args__ = (
        db.UniqueConstraint("user_id", "category_id", "month", name="uq_budget_user_category_month"),
        db.CheckConstraint("amount > 0", name="ck_budget_amount_positive"),
    )

    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    month = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)

    def __repr__(self):
        return f"<Budget {self.amount}>"


# ----------------------------------------------------------------- Recurring

FREQUENCIES = [
    ("daily", "Daily"),
    ("weekly", "Weekly"),
    ("monthly", "Monthly"),
    ("quarterly", "Every 3 Months"),
    ("yearly", "Yearly"),
]


class RecurringTransaction(db.Model):
    """A rule that auto-creates transactions on a schedule (SIP, rent, salary, etc.)."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)          # "SBI SIP", "Netflix"
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    type = db.Column(db.String(7), nullable=False)            # "income" or "expense"
    frequency = db.Column(db.String(20), nullable=False, default="monthly")
    day_of_month = db.Column(db.Integer, nullable=True)       # 1–28 for monthly/quarterly
    next_due = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    payment_mode = db.Column(db.String(20), default="bank_transfer", nullable=False)
    notes = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=True)
    account_id = db.Column(db.Integer, db.ForeignKey("bank_account.id"), nullable=True)

    generated_transactions = db.relationship("Transaction", backref="recurring_rule", foreign_keys=[Transaction.recurring_id])

    def __repr__(self):
        return f"<RecurringTransaction {self.name}>"


# ----------------------------------------------------------------- Password Reset

class PasswordResetToken(db.Model):
    """A one-time token emailed to the user for resetting their password."""

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(32))
    expires_at = db.Column(db.DateTime, nullable=False,
                           default=lambda: datetime.now(timezone.utc) + timedelta(hours=1))
    used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    @property
    def is_valid(self):
        return not self.used and datetime.now(timezone.utc) < self.expires_at.replace(tzinfo=timezone.utc)

    def __repr__(self):
        return f"<PasswordResetToken {self.token[:8]}...>"


# ----------------------------------------------------------------- Sync Receipts

class SyncReceipt(db.Model):
    """Tracks queued offline submissions that reached the server, preventing duplicate entries."""

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    transaction_id = db.Column(db.Integer, db.ForeignKey("transaction.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("user_id", "client_id", name="uq_sync_user_client"),
    )

    def __repr__(self):
        return f"<SyncReceipt {self.client_id}>"


# ----------------------------------------------------------------- Helpers

def add_default_categories(user):
    """Give a brand-new user the starter categories."""
    for kind, names in DEFAULT_CATEGORIES.items():
        for name in names:
            user.categories.append(Category(name=name, type=kind))
