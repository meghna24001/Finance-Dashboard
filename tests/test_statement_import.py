import re
from decimal import Decimal

import pandas as pd

from app import create_app
from config import TestConfig
from models import ImportBatch, Transaction, User, db
from tests.helpers import signup, token


def test_statement_preview_saves_dates_directions_details_and_account_number(tmp_path):
    app = create_app(TestConfig)
    with app.app_context():
        db.drop_all()
        db.create_all()

    statement_path = tmp_path / "statement.xlsx"
    pd.DataFrame([
        ["Account Number: 123456789012"],
        ["Transaction Date", "Description", "Amount", "Type"],
        ["2026-09-02", "Grocery store", "45.50", "debit"],
        ["2026-09-03", "Salary", "1,250.00", "credit"],
    ]).to_excel(statement_path, index=False, header=False)

    client = app.test_client()
    signup(client)
    with statement_path.open("rb") as statement:
        preview = client.post(
            "/transactions/import",
            data={
                "csrf_token": re.search(
                    r'name="csrf_token"[^>]*value="([^"]+)"',
                    client.get("/transactions/import").get_data(as_text=True),
                ).group(1),
                "statement": (statement, statement_path.name),
            },
            content_type="multipart/form-data",
        )

    assert preview.status_code == 200
    assert "123456789012" in preview.get_data(as_text=True)
    commit_token = re.search(
        r'name="csrf_token"[^>]*value="([^"]+)"',
        preview.get_data(as_text=True),
    ).group(1)
    with app.app_context():
        batch = ImportBatch.query.one()

    response = client.post(
        f"/transactions/import/{batch.id}/commit",
        data={"csrf_token": commit_token, "selected": ["0", "1"]},
    )

    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(email="asha@example.com").one()
        transactions = Transaction.query.filter_by(user_id=user.id).order_by(Transaction.date).all()
        assert [
            (item.date.isoformat(), item.type, item.amount, item.description, item.source_account_number)
            for item in transactions
        ] == [
            ("2026-09-02", "expense", Decimal("45.50"), "Grocery store", "123456789012"),
            ("2026-09-03", "income", Decimal("1250.00"), "Salary", "123456789012"),
        ]

    with statement_path.open("rb") as statement:
        matched_preview = client.post(
            "/transactions/import",
            data={
                "csrf_token": token(client, "/transactions/import"),
                "statement": (statement, statement_path.name),
            },
            content_type="multipart/form-data",
        )
    assert "Match: 2026-09-02" in matched_preview.get_data(as_text=True)
    assert "Reconcile" in matched_preview.get_data(as_text=True)
    with app.app_context():
        batch = ImportBatch.query.one()
        transaction_count = Transaction.query.count()
    reconciled = client.post(
        f"/transactions/import/{batch.id}/commit",
        data={
            "csrf_token": re.search(
                r'name="csrf_token"[^>]*value="([^"]+)"',
                matched_preview.get_data(as_text=True),
            ).group(1),
            "reconcile": ["0"],
        },
    )
    assert reconciled.status_code == 302
    with app.app_context():
        assert Transaction.query.count() == transaction_count
        assert Transaction.query.filter_by(description="Grocery store").one().reconciled is True
