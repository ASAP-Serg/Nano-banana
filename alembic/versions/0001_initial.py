"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())

    if "users" not in existing:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("username", sa.String(), nullable=False),
            sa.Column("email", sa.String(), nullable=False),
            sa.Column("hashed_password", sa.String(), nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default=sa.true()),
            sa.Column("is_admin", sa.Boolean(), server_default=sa.false()),
            sa.Column("replicate_api_key", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("last_login", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_users_id", "users", ["id"])
        op.create_index("ix_users_username", "users", ["username"], unique=True)
        op.create_index("ix_users_email", "users", ["email"], unique=True)

    if "generations" not in existing:
        op.create_table(
            "generations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("prompt", sa.Text(), nullable=False),
            sa.Column("enhanced_prompt", sa.Text(), nullable=True),
            sa.Column("negative_prompt", sa.Text(), nullable=True),
            sa.Column("generation_mode", sa.String(), nullable=False),
            sa.Column("model_name", sa.String(), nullable=True),
            sa.Column("resolution", sa.String(), server_default="1K"),
            sa.Column("aspect_ratio", sa.String(), server_default="1:1"),
            sa.Column("guidance_scale", sa.Float(), server_default="7.5"),
            sa.Column("num_inference_steps", sa.Integer(), server_default="50"),
            sa.Column("seed", sa.Integer(), nullable=True),
            sa.Column("output_format", sa.String(), server_default="jpg"),
            sa.Column("result_url", sa.String(), nullable=True),
            sa.Column("result_path", sa.String(), nullable=True),
            sa.Column("result_data", sa.JSON(), nullable=True),
            sa.Column("generation_metadata", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(), server_default="pending"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_generations_id", "generations", ["id"])
        op.create_index("ix_generations_user_id", "generations", ["user_id"])
        op.create_index("ix_generations_status", "generations", ["status"])
        op.create_index("ix_generations_created_at", "generations", ["created_at"])
        op.create_index("ix_generations_model_name", "generations", ["model_name"])
        op.create_index(
            "ix_generations_user_status_created",
            "generations",
            ["user_id", "status", "created_at"],
        )

    if "admin_audit_logs" not in existing:
        op.create_table(
            "admin_audit_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("actor_admin_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("target_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_admin_audit_logs_id", "admin_audit_logs", ["id"])
        op.create_index("ix_admin_audit_logs_actor_admin_id", "admin_audit_logs", ["actor_admin_id"])
        op.create_index("ix_admin_audit_logs_target_user_id", "admin_audit_logs", ["target_user_id"])
        op.create_index("ix_admin_audit_logs_action", "admin_audit_logs", ["action"])
        op.create_index("ix_admin_audit_logs_created_at", "admin_audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("admin_audit_logs")
    op.drop_table("generations")
    op.drop_table("users")
