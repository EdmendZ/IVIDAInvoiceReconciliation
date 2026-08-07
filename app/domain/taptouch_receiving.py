"""Strict inbound contract for authoritative Taptouch receiving snapshots."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.document_sources import UpstreamRecordStatus
from app.domain.documents import LineItem, Party


class TaptouchReceivingPayload(BaseModel):
    """One complete immutable version of a Taptouch receiving record."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    external_tenant_id: str = Field(min_length=1, max_length=255)
    external_brand_id: str | None = Field(default=None, max_length=255)
    external_store_id: str = Field(min_length=1, max_length=255)
    external_supplier_id: str = Field(min_length=1, max_length=255)
    external_receiving_id: str = Field(min_length=1, max_length=255)
    external_version: int = Field(ge=1)
    record_status: UpstreamRecordStatus
    document_number: str = Field(min_length=1, max_length=255)
    received_at: datetime
    currency: str = Field(min_length=3, max_length=3)
    purchase_order_number: str | None = None
    supplier: Party
    location: Party
    items: list[LineItem] = Field(min_length=1)
    upstream_updated_at: datetime

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("received_at", "upstream_updated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Taptouch timestamps must include a timezone")
        return value
