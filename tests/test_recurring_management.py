from datetime import timedelta
from decimal import Decimal

from app import create_app
from config import TestConfig
from finance import today
from models import RecurringTransaction, Transaction, User, db
from tests.helpers import post, signup, text


def test_recurring_reminders_and_duplicate_generation_guard():
    app = create_app(TestConfig)
    client = app.test_client()
    signup(client)
    with app.app_context():
        user = User.query.filter_by(email="asha@example.com").one()
        overdue = RecurringTransaction(
            user_id=user.id,
            name="Late bill",
            amount=Decimal("40"),
            type="expense",
            frequency="monthly",
            next_due=today() - timedelta(days=1),
        )
        upcoming = RecurringTransaction(
            user_id=user.id,
            name="Soon bill",
            amount=Decimal("50"),
            type="expense",
            frequency="monthly",
            next_due=today() + timedelta(days=3),
        )
        db.session.add_all([overdue, upcoming])
        db.session.commit()
        overdue_id = overdue.id
        original_due = overdue.next_due

    page = text(client.get("/recurring"))
    assert "Overdue" in page
    assert "Due soon" in page
    notifications = client.get("/api/notifications").get_json()["notifications"]
    assert any("Late bill is overdue" in notification["message"] for notification in notifications)
    assert any("Soon bill is due" in notification["message"] for notification in notifications)

    first_run = post(client, "/recurring/run", token_from="/recurring", follow=False)
    assert first_run.status_code == 302
    with app.app_context():
        rule = db.session.get(RecurringTransaction, overdue_id)
        assert Transaction.query.count() == 1
        assert Transaction.query.filter_by(recurring_id=overdue_id).count() == 1
        rule.next_due = original_due
        db.session.commit()

    repeat_run = post(client, "/recurring/run", token_from="/recurring", follow=False)
    assert repeat_run.status_code == 302
    with app.app_context():
        assert Transaction.query.filter_by(recurring_id=overdue_id).count() == 1
