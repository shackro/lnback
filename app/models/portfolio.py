from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.entities import Base


class PortfolioLoan(Base):
    __tablename__ = "portfolio_loans"
    __table_args__ = (
        CheckConstraint("principal > 0", name="ck_portfolio_loans_principal_positive"),
        CheckConstraint("outstanding_principal >= 0", name="ck_portfolio_loans_outstanding_nonnegative"),
        CheckConstraint("interest_rate_percent >= 0", name="ck_portfolio_loans_rate_nonnegative"),
        CheckConstraint("term_days > 0", name="ck_portfolio_loans_term_positive"),
        CheckConstraint("max_extensions >= 0", name="ck_portfolio_loans_max_extensions_nonnegative"),
        CheckConstraint("extensions_used >= 0", name="ck_portfolio_loans_extensions_used_nonnegative"),
        CheckConstraint("savings_balance >= 0", name="ck_portfolio_loans_savings_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("loans.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True
    )
    principal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    outstanding_principal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    interest_rate_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    term_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    max_extensions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    extensions_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    savings_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="offer")
    offered_by: Mapped[str] = mapped_column(String(254), nullable=False)
    inspection_confirmed_by: Mapped[str | None] = mapped_column(String(254))
    inspection_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    borrower_accepted_by: Mapped[str | None] = mapped_column(String(254))
    borrower_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disbursed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    maturity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    assessed_sale_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    buyout_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    buyout_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PortfolioTransaction(Base):
    __tablename__ = "portfolio_transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_portfolio_transactions_amount_positive"),
        UniqueConstraint("provider_reference", name="uq_portfolio_transactions_provider_reference"),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'failed')",
            name="ck_portfolio_transactions_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    portfolio_loan_id: Mapped[str] = mapped_column(
        ForeignKey("portfolio_loans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(80))
    provider_checkout_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="confirmed")
    actor_email: Mapped[str | None] = mapped_column(String(254))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PortfolioCapitalEntry(Base):
    __tablename__ = "portfolio_capital_entries"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_portfolio_capital_entries_amount_positive"),
        UniqueConstraint("provider_reference", name="uq_portfolio_capital_entries_provider_reference"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    provider_reference: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_email: Mapped[str] = mapped_column(String(254), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PortfolioNotification(Base):
    __tablename__ = "portfolio_notifications"
    __table_args__ = (
        UniqueConstraint("portfolio_loan_id", "period_number", "kind", name="uq_portfolio_notification_cycle"),
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'cancelled')",
            name="ck_portfolio_notifications_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    portfolio_loan_id: Mapped[str] = mapped_column(
        ForeignKey("portfolio_loans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    period_number: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")
    provider_reference: Mapped[str | None] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PortfolioCoupon(Base):
    __tablename__ = "portfolio_coupons"
    __table_args__ = (
        CheckConstraint("discount_value > 0", name="ck_portfolio_coupons_value_positive"),
        CheckConstraint("redemption_count >= 0", name="ck_portfolio_coupons_redemption_nonnegative"),
        CheckConstraint("max_redemptions IS NULL OR max_redemptions > 0", name="ck_portfolio_coupons_max_redemptions"),
    )

    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    discount_type: Mapped[str] = mapped_column(String(12), nullable=False)
    discount_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    redemption_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(254), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PortfolioCouponRedemption(Base):
    __tablename__ = "portfolio_coupon_redemptions"
    __table_args__ = (
        CheckConstraint("discount_amount > 0", name="ck_portfolio_coupon_redemptions_amount_positive"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    coupon_code: Mapped[str] = mapped_column(
        ForeignKey("portfolio_coupons.code", ondelete="RESTRICT"), nullable=False, index=True
    )
    portfolio_loan_id: Mapped[str] = mapped_column(
        ForeignKey("portfolio_loans.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
