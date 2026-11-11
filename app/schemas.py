import re
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


def normalize_kenyan_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if re.fullmatch(r"254[17]\d{8}", digits):
        return digits
    if re.fullmatch(r"0[17]\d{8}", digits):
        return f"254{digits[1:]}"
    if re.fullmatch(r"[17]\d{8}", digits):
        return f"254{digits}"
    raise ValueError("Enter a valid Kenyan mobile number")


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        from_attributes=True,
        populate_by_name=True,
        extra="forbid",
    )


class ProductSchema(ApiModel):
    id: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=80)
    description: str
    diagnostic_notes: str = ""
    original_value: float = Field(gt=0)
    price: float = Field(gt=0)
    condition: Literal["A", "B", "C"]
    status: Literal["available", "reserved", "sold"] = "available"
    location: str = Field(min_length=1, max_length=120)
    image: str = Field(min_length=1)
    images: list[str] = Field(default_factory=list, max_length=5)
    inspection_video_url: str | None = Field(default=None, max_length=2048)
    created_at: datetime | None = None

    @field_validator("title", "category", "description", "diagnostic_notes", "location", "image")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("images")
    @classmethod
    def strip_image_urls(cls, value: list[str]) -> list[str]:
        return [image.strip() for image in value if image.strip()]

    @field_validator("inspection_video_url")
    @classmethod
    def strip_video_url(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("price")
    @classmethod
    def price_is_not_above_original_value(cls, value: float, info: ValidationInfo) -> float:
        original_value = info.data.get("original_value")
        if original_value is not None and value > original_value:
            raise ValueError("Price cannot exceed original value")
        return value


class ProductUpdateRequest(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=80)
    description: str
    diagnostic_notes: str = ""
    original_value: float = Field(gt=0)
    price: float = Field(gt=0)
    condition: Literal["A", "B", "C"]
    location: str = Field(min_length=1, max_length=120)
    image: str = Field(min_length=1)
    images: list[str] = Field(default_factory=list, max_length=5)
    inspection_video_url: str | None = Field(default=None, max_length=2048)

    @field_validator("title", "category", "description", "diagnostic_notes", "location", "image")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("images")
    @classmethod
    def strip_image_urls(cls, value: list[str]) -> list[str]:
        return [image.strip() for image in value if image.strip()]

    @field_validator("inspection_video_url")
    @classmethod
    def strip_video_url(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("price")
    @classmethod
    def price_is_not_above_original_value(cls, value: float, info: ValidationInfo) -> float:
        original_value = info.data.get("original_value")
        if original_value is not None and value > original_value:
            raise ValueError("Price cannot exceed original value")
        return value


class BidSchema(ApiModel):
    id: str = Field(min_length=1, max_length=40)
    product_id: str
    bidder_phone: str
    amount: float = Field(gt=0)
    status: Literal["pending", "confirmed", "rejected"] = "pending"
    referral_code: str | None = None
    created_at: datetime | None = None

    @field_validator("bidder_phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_kenyan_phone(value)


class LoanSchema(ApiModel):
    id: str = Field(min_length=1, max_length=40)
    borrower_name: str = Field(min_length=1, max_length=100)
    national_id: str = Field(min_length=1, max_length=30)
    phone: str
    collateral: str = Field(min_length=1)
    principal: float = Field(ge=1000)
    term_months: int = Field(ge=1, le=6)
    status: Literal["submitted", "reviewing", "approved", "disbursed", "declined", "settled"] = "submitted"
    referral_code: str | None = None
    created_at: datetime | None = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_kenyan_phone(value)


class ReferralSchema(ApiModel):
    id: str
    referral_code: str
    kind: Literal["buy", "loan"]
    reference_id: str
    amount: float
    status: Literal["pending", "paid"]
    created_at: datetime


class PublicBidSchema(ApiModel):
    id: str
    product_id: str
    amount: float
    status: Literal["pending", "confirmed", "rejected"]
    created_at: datetime


class PublicStoreSchema(ApiModel):
    products: list[ProductSchema]
    bids: list[PublicBidSchema]
    monthly_rate: float | None
    whatsapp_number: str


class BidCreateRequest(ApiModel):
    id: str = Field(min_length=1, max_length=40)
    product_id: str
    bidder_phone: str
    amount: int = Field(gt=0)
    referral_code: str | None = None

    @field_validator("bidder_phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_kenyan_phone(value)


class LoanCreateRequest(ApiModel):
    id: str = Field(min_length=1, max_length=40)
    borrower_name: str = Field(min_length=1, max_length=100)
    national_id: str = Field(min_length=1, max_length=30)
    phone: str
    collateral: str = Field(min_length=1)
    principal: int = Field(ge=1000)
    term_months: int = Field(ge=1, le=6)
    referral_code: str | None = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_kenyan_phone(value)


class InquiryContactRequest(ApiModel):
    contact_name: str = Field(min_length=1, max_length=100)
    phone: str
    consent: Literal[True]

    @field_validator("contact_name")
    @classmethod
    def strip_contact_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Enter your name")
        return cleaned

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_kenyan_phone(value)


class AssetFinanceInquiryRequest(InquiryContactRequest):
    kind: Literal["asset_finance"]
    asset_category: str = Field(min_length=1, max_length=80)
    asset_details: dict[str, str] = Field(default_factory=dict, max_length=8)
    condition_grade: Literal["A", "B", "C"]
    condition_notes: str = Field(default="", max_length=1000)
    estimated_amount: float | None = Field(default=None, gt=0, le=100_000_000)
    preferred_inspection_time: str = Field(default="", max_length=120)
    referral_code: str | None = Field(default=None, max_length=30)

    @field_validator("asset_category")
    @classmethod
    def strip_asset_category(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Enter an asset category")
        return cleaned

    @field_validator("condition_notes", "preferred_inspection_time")
    @classmethod
    def strip_optional_inquiry_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("asset_details")
    @classmethod
    def validate_asset_details(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for key, detail in value.items():
            clean_key = key.strip()
            clean_detail = detail.strip()
            if not clean_key or len(clean_key) > 40 or len(clean_detail) > 160:
                raise ValueError("Asset details must have short labels and values")
            if clean_detail:
                cleaned[clean_key] = clean_detail
        return cleaned


class ProductInquiryRequest(InquiryContactRequest):
    kind: Literal["product"]
    product_id: str = Field(min_length=1, max_length=40)
    referral_code: str | None = Field(default=None, max_length=30)

    @field_validator("product_id")
    @classmethod
    def strip_product_id(cls, value: str) -> str:
        return value.strip()


class InquirySchema(ApiModel):
    id: str
    kind: Literal["asset_finance", "product"]
    contact_name: str
    phone: str
    context: dict[str, object]
    status: Literal["new", "contacted", "closed"]
    consented_at: datetime
    created_at: datetime


class InquiryStatusRequest(ApiModel):
    status: Literal["new", "contacted", "closed"]


AdminPermission = Literal[
    "dashboard.read",
    "inventory.manage",
    "holds.manage",
    "loans.manage",
    "inquiries.manage",
    "payouts.manage",
    "portfolio.manage",
    "settings.manage",
]


class AdminCreateRequest(ApiModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=12, max_length=256)
    permissions: list[AdminPermission] = Field(default_factory=lambda: ["dashboard.read"])

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Enter a valid email address")
        return normalized

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, value: list[AdminPermission]) -> list[AdminPermission]:
        if "dashboard.read" not in value:
            raise ValueError("The dashboard.read permission is required")
        if len(set(value)) != len(value):
            raise ValueError("Permissions cannot contain duplicates")
        return value


class AdminPermissionUpdateRequest(ApiModel):
    permissions: list[AdminPermission]

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, value: list[AdminPermission]) -> list[AdminPermission]:
        if "dashboard.read" not in value:
            raise ValueError("The dashboard.read permission is required")
        if len(set(value)) != len(value):
            raise ValueError("Permissions cannot contain duplicates")
        return value


class AdminPasswordChangeRequest(ApiModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)

    @field_validator("new_password")
    @classmethod
    def require_new_password(cls, value: str, info: ValidationInfo) -> str:
        if value == info.data.get("current_password"):
            raise ValueError("Choose a password different from the current password")
        return value


class AdminUserSchema(ApiModel):
    id: int
    email: str
    role: Literal["admin", "super_admin"]
    permissions: list[str]


class AdminAuditSchema(ApiModel):
    id: int
    actor_email: str
    action: str
    target_admin_email: str
    details: dict[str, object]
    created_at: datetime


class AdminMeSchema(ApiModel):
    email: str
    role: Literal["admin", "super_admin"]
    permissions: list[str]


class StoreSchema(ApiModel):
    products: list[ProductSchema]
    bids: list[BidSchema]
    loans: list[LoanSchema]
    inquiries: list[InquirySchema]
    referrals: list[ReferralSchema]
    monthly_rate: float | None
    whatsapp_number: str


class BidResolveRequest(ApiModel):
    action: Literal["confirm", "reject"]


class LoanStatusRequest(ApiModel):
    status: Literal["reviewing", "approved", "disbursed", "declined", "settled"]


class SellProductRequest(ApiModel):
    referral_code: str | None = Field(default=None, pattern=r"^RF\d{6}$")


class SettingsRequest(ApiModel):
    monthly_rate: float | None = Field(default=None, ge=0, le=100)
    whatsapp_number: str = Field(min_length=12, max_length=15)

    @field_validator("whatsapp_number")
    @classmethod
    def validate_whatsapp_number(cls, value: str) -> str:
        return normalize_kenyan_phone(value)


class PortfolioOfferRequest(ApiModel):
    principal: Decimal = Field(ge=Decimal("1000.00"), max_digits=12, decimal_places=2)
    interest_rate_percent: Decimal = Field(ge=Decimal("0"), le=Decimal("100"), max_digits=7, decimal_places=4)
    term_days: int = Field(default=14, ge=1, le=365)
    max_extensions: int = Field(default=1, ge=0, le=24)
    buyout_window_days: int = Field(default=7, ge=1, le=60)


class PortfolioAcceptanceRequest(ApiModel):
    inspection_confirmed: Literal[True]
    borrower_accepted: Literal[True]


class PortfolioSaleAssessmentRequest(ApiModel):
    assessed_sale_price: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)


class PortfolioReceiptRequest(ApiModel):
    amount: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)
    provider_reference: str = Field(min_length=1, max_length=80)


class PortfolioCapitalInjectionRequest(PortfolioReceiptRequest):
    note: str | None = Field(default=None, max_length=500)


class PortfolioExtensionRequest(ApiModel):
    source: Literal["mpesa", "savings"]
    amount: Decimal | None = Field(default=None, gt=Decimal("0"), max_digits=12, decimal_places=2)
    provider_reference: str | None = Field(default=None, min_length=1, max_length=80)


class PortfolioSettlementRequest(ApiModel):
    amount: Decimal = Field(ge=Decimal("0"), max_digits=12, decimal_places=2)
    apply_savings: bool = False
    coupon_code: str | None = Field(default=None, min_length=1, max_length=40)
    provider_reference: str | None = Field(default=None, min_length=1, max_length=80)


class PortfolioCouponRequest(ApiModel):
    code: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    discount_type: Literal["fixed", "percent"]
    discount_value: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)
    max_redemptions: int | None = Field(default=1, ge=1, le=10000)
    expires_at: datetime | None = None

    @field_validator("discount_value")
    @classmethod
    def validate_percent_discount(cls, value: Decimal, info: ValidationInfo) -> Decimal:
        if info.data.get("discount_type") == "percent" and value > Decimal("100"):
            raise ValueError("Percentage coupons cannot exceed 100%")
        return value


class PortfolioCollateralSaleRequest(ApiModel):
    amount: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)
    provider_reference: str = Field(min_length=1, max_length=80)


class PortfolioDisbursementConfirmationRequest(ApiModel):
    provider_reference: str = Field(min_length=1, max_length=80)


class PortfolioQuoteResponse(ApiModel):
    portfolio_loan_id: str
    status: str
    principal: Decimal
    outstanding_principal: Decimal
    interest_rate_percent: Decimal
    term_days: int
    period_interest_due: Decimal
    full_payoff_before_savings_or_coupon: Decimal
    savings_balance: Decimal
    extensions_remaining: int
    assessed_sale_price: Decimal | None
    buyout_price_before_savings: Decimal | None
    maturity_at: datetime | None
    coupon_discount: Decimal = Decimal("0.00")
    payoff_after_savings_and_coupon: Decimal | None = None


class PortfolioAdminLoanResponse(PortfolioQuoteResponse):
    application_id: str
    borrower_name: str
    borrower_phone: str
    collateral: str
    max_extensions: int
    buyout_window_days: int
    inspection_confirmed_at: datetime | None
    borrower_accepted_at: datetime | None
