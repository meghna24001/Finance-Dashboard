"""Simulates adding and editing bank accounts and wallets."""
from app import create_app
from config import TestConfig
from models import BankAccount, User
from tests.helpers import check, finish, flash_text, post, signup, text

app = create_app(TestConfig)
client = app.test_client()
signup(client)
email = "asha@example.com"

response = post(
    client,
    "/accounts/new",
    {
        "name": "Everyday account",
        "account_type": "savings",
        "last4": "1234",
        "color": "#10b981",
        "balance_hint": "2500",
    },
    token_from="/accounts",
)
check("Saving an account confirms it was added", flash_text(text(response)) == "Account added.")

with app.app_context():
    user = User.query.filter_by(email=email).one()
    account = BankAccount.query.filter_by(user_id=user.id).one()
    account_id = account.id

edit_url = f"/accounts/{account_id}/edit"
index = text(client.get("/accounts"))
check(
    "Account card has a working Edit link",
    f'href="{edit_url}" aria-label="Edit Everyday account"' in index,
)
edit_page = text(client.get(edit_url))
check(
    "Edit page is prefilled and selects the saved color",
    'value="Everyday account"' in edit_page and 'value="#10b981" selected' in edit_page,
)

invalid = post(
    client,
    edit_url,
    {
        "name": "Everyday account",
        "account_type": "savings",
        "last4": "12",
        "color": "#f59e0b",
        "balance_hint": "2500",
    },
    token_from=edit_url,
)
check("Edit form retains the chosen color after validation errors", 'value="#f59e0b" selected' in text(invalid))

updated = post(
    client,
    edit_url,
    {
        "name": "Main account",
        "account_type": "current",
        "last4": "4321",
        "color": "#f59e0b",
        "balance_hint": "3000",
    },
    token_from=edit_url,
)
check("Saving edits updates the account", flash_text(text(updated)) == "Account updated.")
with app.app_context():
    account = BankAccount.query.filter_by(id=account_id).one()
    check(
        "Saved account details persist",
        (account.name, account.account_type, account.last4, account.color)
        == ("Main account", "current", "4321", "#f59e0b"),
    )

finish()
