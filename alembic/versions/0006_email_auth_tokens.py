"""Email verification and password-reset tokens.

Revision ID: 0006_email_auth_tokens
Revises: 0005_trusted_devices_google
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_email_auth_tokens"
down_revision = "0005_trusted_devices_google"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "auth_email_tokens" not in tables:
        op.create_table(
            "auth_email_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("purpose", sa.String(), nullable=False),
            sa.Column("token_hash", sa.String(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("token_hash", name="uq_auth_email_tokens_hash"),
        )
        op.create_index("ix_auth_email_tokens_user_id", "auth_email_tokens", ["user_id"])
        op.create_index("ix_auth_email_tokens_purpose", "auth_email_tokens", ["purpose"])
    # Existing accounts stay usable after enabling email verification.
    if "users" in tables:
        cols = {c["name"] for c in inspector.get_columns("users")}
        if "email_verified" in cols:
            op.execute(sa.text("UPDATE users SET email_verified = true WHERE email_verified IS NOT TRUE"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "auth_email_tokens" in set(inspector.get_table_names()):
        op.drop_table("auth_email_tokens")
