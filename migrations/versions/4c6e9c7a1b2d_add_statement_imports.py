"""Add statement import batches and transaction fingerprints.

Revision ID: 4c6e9c7a1b2d
Revises: d8593e215a8f
"""
from alembic import op
import sqlalchemy as sa


revision = "4c6e9c7a1b2d"
down_revision = "d8593e215a8f"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("transaction") as batch_op:
        batch_op.add_column(sa.Column("source_fingerprint", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("source_account_number", sa.String(length=40), nullable=True))
        batch_op.create_unique_constraint(
            "uq_transaction_user_source_fingerprint",
            ["user_id", "source_fingerprint"],
        )
    op.create_table(
        "import_batch",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("rows_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("import_batch")
    with op.batch_alter_table("transaction") as batch_op:
        batch_op.drop_constraint("uq_transaction_user_source_fingerprint", type_="unique")
        batch_op.drop_column("source_account_number")
        batch_op.drop_column("source_fingerprint")
