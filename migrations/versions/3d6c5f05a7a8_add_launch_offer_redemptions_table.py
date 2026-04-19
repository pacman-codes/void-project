"""add launch_offer_redemptions table

Revision ID: 3d6c5f05a7a8
Revises: 8bd2a3cdc9f5
Create Date: 2026-04-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3d6c5f05a7a8"
down_revision: Union[str, None] = "8bd2a3cdc9f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "launch_offer_redemptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("payment_id", sa.String(length=255), nullable=False),
        sa.Column("plan_code", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        "ix_launch_offer_redemptions_telegram_id",
        "launch_offer_redemptions",
        ["telegram_id"],
        unique=False,
    )
    op.create_index(
        "ix_launch_offer_redemptions_payment_id",
        "launch_offer_redemptions",
        ["payment_id"],
        unique=True,
    )
    op.create_index(
        "ix_launch_offer_redemptions_created_at",
        "launch_offer_redemptions",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_launch_offer_redemptions_created_at", table_name="launch_offer_redemptions")
    op.drop_index("ix_launch_offer_redemptions_payment_id", table_name="launch_offer_redemptions")
    op.drop_index("ix_launch_offer_redemptions_telegram_id", table_name="launch_offer_redemptions")
    op.drop_table("launch_offer_redemptions")
