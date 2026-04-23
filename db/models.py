from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)
    subscription_expiry: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    traffic_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    traffic_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)

    trial_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    access_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    terms_accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    payment_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payment_plan_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payment_devices_to_add: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payment_confirmation_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_promo_code: Mapped[str | None] = mapped_column(String(100), nullable=True)

    promo_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    promo_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    partner_offer_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    partner_offer_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    first_paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    device_limit: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    used_devices: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    vpn_accesses: Mapped[list["VpnAccess"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class VpnAccess(Base):
    __tablename__ = "vpn_accesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    server_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_uuid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    device_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    device_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    user: Mapped["User"] = relationship(back_populates="vpn_accesses")


VPNAccess = VpnAccess
