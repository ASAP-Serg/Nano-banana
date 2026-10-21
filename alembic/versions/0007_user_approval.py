"""User admin-approval flag + legacy email re-verify.

Revision ID: 0007_user_approval
Revises: 0006_email_auth_tokens
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_user_approval"
down_revision = "0006_email_auth_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "is_approved" not in cols:
        op.add_column(
            "users",
            sa.Column("is_approved", sa.Boolean(), server_default=sa.false(), nullable=False),
        )
    # Everyone already in DB is a known colleague — keep access.
    op.execute(sa.text("UPDATE users SET is_approved = true WHERE is_approved IS NOT TRUE"))
    # Password accounts (non-admin) must confirm email once under the new mail flow.
    # Google-linked and admins stay verified.
    op.execute(
        sa.text(
            """
            UPDATE users
            SET email_verified = false
            WHERE is_admin IS NOT TRUE
              AND google_sub IS NULL
              AND (hashed_password IS NOT NULL)
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "is_approved" in cols:
        op.drop_column("users", "is_approved")
