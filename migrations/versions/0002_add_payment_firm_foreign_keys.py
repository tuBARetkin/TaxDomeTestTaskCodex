"""Add payment payer and payee foreign keys to firms.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The earlier local draft of 0001 already included these constraints.
    op.execute(
        "ALTER TABLE payments "
        "DROP CONSTRAINT IF EXISTS payments_payer_firm_id_fkey, "
        "DROP CONSTRAINT IF EXISTS payments_payee_firm_id_fkey"
    )
    op.create_foreign_key(
        "payments_payer_firm_id_fkey",
        "payments",
        "firms",
        ["payer_firm_id"],
        ["id"],
    )
    op.create_foreign_key(
        "payments_payee_firm_id_fkey",
        "payments",
        "firms",
        ["payee_firm_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("payments_payee_firm_id_fkey", "payments", type_="foreignkey")
    op.drop_constraint("payments_payer_firm_id_fkey", "payments", type_="foreignkey")
