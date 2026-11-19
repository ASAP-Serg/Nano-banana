"""Add is_superadmin owner flag.

Revision ID: 0008_superadmin
Revises: 0007_user_approval
Create Date: 2026-11-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_superadmin"
down_revision = "0007_user_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "is_superadmin" not in cols:
        op.add_column(
            "users",
            sa.Column("is_superadmin", sa.Boolean(), server_default=sa.false(), nullable=False),
        )
    # Promote the oldest active admin to superadmin if none yet.
    op.execute(
        sa.text(
            """
            UPDATE users
            SET is_superadmin = true, is_admin = true
            WHERE id = (
              SELECT id FROM users
              WHERE is_admin IS TRUE AND is_active IS TRUE
              ORDER BY id ASC
              LIMIT 1
            )
            AND NOT EXISTS (SELECT 1 FROM users WHERE is_superadmin IS TRUE)
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "is_superadmin" in cols:
        op.drop_column("users", "is_superadmin")
