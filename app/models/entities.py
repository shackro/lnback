from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Float, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="admin")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price > 0", name="ck_products_price_positive"),
        CheckConstraint("original_value >= price", name="ck_products_original_value"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    diagnostic_notes: Mapped[str] = mapped_column(Text, nullable=False)
    original_value: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    condition: Mapped[str] = mapped_column(String(1), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="available", index=True)
    location: Mapped[str] = mapped_column(String(120), nullable=False)
    image: Mapped[str] = mapped_column(Text, nullable=False)
    images: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    inspection_video_url: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Bid(Base):
    __tablename__ = "bids"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_bids_amount_positive"),
        CheckConstraint("status IN ('pending', 'confirmed', 'rejected')", name="ck_bids_status"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    bidder_phone: Mapped[str] = mapped_column(String(15), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    referral_code: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Loan(Base):
    __tablename__ = "loans"
    __table_args__ = (
        CheckConstraint("principal >= 1000", name="ck_loans_principal_minimum"),
        CheckConstraint(
            "status IN ('submitted', 'reviewing', 'approved', 'disbursed', 'declined', 'settled')",
            name="ck_loans_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    borrower_name: Mapped[str] = mapped_column(String(100), nullable=False)
    national_id: Mapped[str] = mapped_column(String(30), nullable=False)
    phone: Mapped[str] = mapped_column(String(15), nullable=False)
    collateral: Mapped[str] = mapped_column(Text, nullable=False)
    principal: Mapped[float] = mapped_column(Float, nullable=False)
    term_months: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="submitted", index=True)
    referral_code: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Referral(Base):
    __tablename__ = "referrals"
    __table_args__ = (UniqueConstraint("kind", "reference_id", name="uq_referrals_kind_reference"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    referral_code: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(40), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SettingsRecord(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    monthly_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    whatsapp_number: Mapped[str] = mapped_column(String(15), nullable=False, default="254700000000")
