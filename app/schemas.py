import re
from datetime import datetime
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


class StoreSchema(ApiModel):
    products: list[ProductSchema]
    bids: list[BidSchema]
    loans: list[LoanSchema]
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
