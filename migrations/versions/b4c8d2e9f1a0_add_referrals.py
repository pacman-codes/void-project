"""add referrals table

Revision ID: b4c8d2e9f1a0
Revises: a7c9e1b2d3f4
Create Date: 2026-05-13
"""

from alembic import op
import sqlalchemy as sa


revision = "b4c8d2e9f1a0"
down_revision = "a7c9e1b2d3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "referrals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("referrer_user_id", sa.Integer(), nullable=False),
        sa.Column("referred_user_id", sa.Integer(), nullable=False),
        sa.Column("referred_paid_at", sa.DateTime(), nullable=True),
        sa.Column("bonus_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payment_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["referred_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["referrer_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("referred_user_id", name="uq_referrals_referred_user_id"),
        sa.CheckConstraint("referrer_user_id <> referred_user_id", name="ck_referrals_no_self_referral"),
    )
    op.create_index(op.f("ix_referrals_referrer_user_id"), "referrals", ["referrer_user_id"], unique=False)
    op.create_index(op.f("ix_referrals_referred_user_id"), "referrals", ["referred_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_referrals_referred_user_id"), table_name="referrals")
    op.drop_index(op.f("ix_referrals_referrer_user_id"), table_name="referrals")
    op.drop_table("referrals")
