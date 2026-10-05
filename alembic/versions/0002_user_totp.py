"""Add TOTP columns on users

Revision ID: 0002_user_totp
Revises: 0001_initial
Create Date: 2026-10-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_user_totp"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "users" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "totp_secret" not in cols:
        op.add_column("users", sa.Column("totp_secret", sa.String(), nullable=True))
    if "totp_enabled" not in cols:
        op.add_column(
            "users",
            sa.Column("totp_enabled", sa.Boolean(), server_default=sa.false(), nullable=True),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "users" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "totp_enabled" in cols:
        op.drop_column("users", "totp_enabled")
    if "totp_secret" in cols:
        op.drop_column("users", "totp_secret")
