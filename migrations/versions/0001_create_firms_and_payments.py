"""Create firms and payments."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "firms",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("balance_cents", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="firms_pkey"),
        sa.UniqueConstraint("uuid", name="firms_uuid_key"),
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("payer_firm_id", sa.Integer(), nullable=False),
        sa.Column("payee_firm_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="payments_pkey"),
    )


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_table("firms")
