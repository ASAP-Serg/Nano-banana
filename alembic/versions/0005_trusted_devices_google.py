"""Trusted devices + Google OAuth columns.

Revision ID: 0005_trusted_devices_google
Revises: 0004_token_version
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_trusted_devices_google"
down_revision = "0004_token_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" in tables:
        cols = {c["name"] for c in inspector.get_columns("users")}
        if "google_sub" not in cols:
            op.add_column("users", sa.Column("google_sub", sa.String(), nullable=True))
            op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)
        if "email_verified" not in cols:
            op.add_column(
                "users",
                sa.Column("email_verified", sa.Boolean(), server_default=sa.false(), nullable=False),
            )
        # Allow Google-only accounts without a local password.
        if "hashed_password" in cols:
            op.alter_column("users", "hashed_password", existing_type=sa.String(), nullable=True)

    if "trusted_devices" not in tables:
        op.create_table(
            "trusted_devices",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash", sa.String(), nullable=False),
            sa.Column("label", sa.String(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("token_hash", name="uq_trusted_devices_token_hash"),
        )
        op.create_index("ix_trusted_devices_user_id", "trusted_devices", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "trusted_devices" in tables:
        op.drop_table("trusted_devices")

    if "users" in tables:
        cols = {c["name"] for c in inspector.get_columns("users")}
        if "email_verified" in cols:
            op.drop_column("users", "email_verified")
        if "google_sub" in cols:
            op.drop_index("ix_users_google_sub", table_name="users")
            op.drop_column("users", "google_sub")
        if "hashed_password" in cols:
            op.alter_column("users", "hashed_password", existing_type=sa.String(), nullable=False)
