"""add user subscription links

Revision ID: 9a2b1c7d4e6f
Revises: 3d6c5f05a7a8
Create Date: 2026-05-06
"""

from alembic import op
import sqlalchemy as sa


revision = "9a2b1c7d4e6f"
down_revision = "3d6c5f05a7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_subscription_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("migrated_at", sa.DateTime(), nullable=True),
        sa.Column("raw_disable_after", sa.DateTime(), nullable=True),
        sa.Column("token_rotated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_subscription_links_user_id",
        "user_subscription_links",
        ["user_id"],
    )
    op.create_index(
        "ix_user_subscription_links_token",
        "user_subscription_links",
        ["token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_user_subscription_links_token", table_name="user_subscription_links")
    op.drop_index("ix_user_subscription_links_user_id", table_name="user_subscription_links")
    op.drop_table("user_subscription_links")
