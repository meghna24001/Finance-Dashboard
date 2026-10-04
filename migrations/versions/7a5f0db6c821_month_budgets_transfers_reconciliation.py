"""Add month-specific budgets, transfers, and reconciliation state.

Revision ID: 7a5f0db6c821
Revises: 4c6e9c7a1b2d
"""
from datetime import date, datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "7a5f0db6c821"
down_revision = "4c6e9c7a1b2d"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()

    with op.batch_alter_table("budget") as batch_op:
        batch_op.drop_constraint("uq_budget_user_category", type_="unique")
        batch_op.add_column(sa.Column("month", sa.Date(), nullable=True))

    budgets = connection.execute(sa.text("SELECT id, created_at FROM budget")).fetchall()
    for budget_id, created_at in budgets:
        created = created_at or datetime.now(timezone.utc)
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        connection.execute(
            sa.text("UPDATE budget SET month = :month WHERE id = :id"),
            {"month": date(created.year, created.month, 1), "id": budget_id},
        )

    with op.batch_alter_table("budget") as batch_op:
        batch_op.alter_column("month", existing_type=sa.Date(), nullable=False)
        batch_op.create_unique_constraint(
            "uq_budget_user_category_month", ["user_id", "category_id", "month"]
        )

    with op.batch_alter_table("transaction") as batch_op:
        batch_op.drop_constraint("ck_transaction_type", type_="check")
        batch_op.create_check_constraint(
            "ck_transaction_type", "type IN ('income', 'expense', 'transfer')"
        )
        batch_op.add_column(sa.Column("transfer_to_account_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("recurring_due_date", sa.Date(), nullable=True))
        batch_op.add_column(
            sa.Column("reconciled", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.create_foreign_key(
            "fk_transaction_transfer_to_account_id_bank_account",
            "bank_account",
            ["transfer_to_account_id"],
            ["id"],
        )

    generated = connection.execute(
        sa.text(
            'SELECT id, recurring_id, date FROM "transaction" '
            "WHERE recurring_id IS NOT NULL ORDER BY recurring_id, date, id"
        )
    ).fetchall()
    seen = set()
    for transaction_id, recurring_id, transaction_date in generated:
        key = (recurring_id, transaction_date)
        if key not in seen:
            connection.execute(
                sa.text(
                    'UPDATE "transaction" SET recurring_due_date = :due_date WHERE id = :id'
                ),
                {"due_date": transaction_date, "id": transaction_id},
            )
            seen.add(key)

    with op.batch_alter_table("transaction") as batch_op:
        batch_op.create_unique_constraint(
            "uq_transaction_recurring_due", ["recurring_id", "recurring_due_date"]
        )


def downgrade():
    with op.batch_alter_table("transaction") as batch_op:
        batch_op.drop_constraint("uq_transaction_recurring_due", type_="unique")
        batch_op.drop_constraint(
            "fk_transaction_transfer_to_account_id_bank_account", type_="foreignkey"
        )
        batch_op.drop_column("reconciled")
        batch_op.drop_column("recurring_due_date")
        batch_op.drop_column("transfer_to_account_id")
        batch_op.drop_constraint("ck_transaction_type", type_="check")
        batch_op.create_check_constraint(
            "ck_transaction_type", "type IN ('income', 'expense')"
        )

    with op.batch_alter_table("budget") as batch_op:
        batch_op.drop_constraint("uq_budget_user_category_month", type_="unique")
        batch_op.drop_column("month")
        batch_op.create_unique_constraint(
            "uq_budget_user_category", ["user_id", "category_id"]
        )
