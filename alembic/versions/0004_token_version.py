"""Add token_version for JWT revocation on password change.

Revision ID: 0004_token_version
Revises: 0003_mosaic_operator
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_token_version"
down_revision = "0003_mosaic_operator"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "users" not in tables:
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "token_version" not in cols:
        op.add_column(
            "users",
            sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "users" not in tables:
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "token_version" in cols:
        op.drop_column("users", "token_version")
