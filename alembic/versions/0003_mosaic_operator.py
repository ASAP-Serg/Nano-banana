"""Operator flag and admin-editable mosaic prompts.

Revision ID: 0003_mosaic_operator
Revises: 0002_user_totp
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_mosaic_operator"
down_revision = "0002_user_totp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "users" in tables:
        cols = {c["name"] for c in inspector.get_columns("users")}
        if "is_operator" not in cols:
            op.add_column(
                "users",
                sa.Column("is_operator", sa.Boolean(), server_default=sa.false(), nullable=False),
            )
    if "mosaic_prompts" not in tables:
        op.create_table(
            "mosaic_prompts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("mode", sa.String(), nullable=False),
            sa.Column("variant", sa.String(), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.UniqueConstraint("mode", "variant", name="uq_mosaic_prompt_slot"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "mosaic_prompts" in tables:
        op.drop_table("mosaic_prompts")
    if "users" in tables:
        cols = {c["name"] for c in inspector.get_columns("users")}
        if "is_operator" in cols:
            op.drop_column("users", "is_operator")
