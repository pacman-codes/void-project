"""add paid traffic period fields

Revision ID: c1d2e3f4a5b6
Revises: b4c8d2e9f1a0
Create Date: 2026-05-14
"""

from alembic import op
import sqlalchemy as sa


revision = "c1d2e3f4a5b6"
down_revision = "b4c8d2e9f1a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("traffic_period_started_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("traffic_period_base_mb", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("traffic_period_panel_total_mb", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("traffic_overuse_notified_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "traffic_overuse_notified_at")
    op.drop_column("users", "traffic_period_panel_total_mb")
    op.drop_column("users", "traffic_period_base_mb")
    op.drop_column("users", "traffic_period_started_at")
