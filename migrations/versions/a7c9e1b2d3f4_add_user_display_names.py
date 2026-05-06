"""add user display names

Revision ID: a7c9e1b2d3f4
Revises: 9a2b1c7d4e6f
Create Date: 2026-05-06
"""

from alembic import op
import sqlalchemy as sa


revision = "a7c9e1b2d3f4"
down_revision = "9a2b1c7d4e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("first_name", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
