"""Invoice 与 Receive Note 共用的规范化业务模型。

这些模型是模型输出、人工审核和最终核对之间的稳定契约。基础设施层可以变化，
但进入业务规则的数据必须先通过这里的类型和数值约束。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DocumentType(StrEnum):
    """系统支持的两类采购业务单据。"""

    INVOICE = "invoice"
    RECEIVE_NOTE = "receive_note"


class Party(BaseModel):
    """供应商或门店等商业主体的最小身份信息。"""

    name: str
    business_number: str | None = None
    address: str | None = None


class LineItem(BaseModel):
    """单据商品行；quantity 必须为正，未知价格使用 None 而不是 0。"""

    line_number: str | None = None
    sku: str | None = None
    description: str
    quantity: Decimal = Field(gt=0)
    unit: str | None = None
    tax_code: str | None = None
    unit_price: Decimal | None = Field(default=None, ge=0)
    tax_amount: Decimal | None = Field(default=None, ge=0)
    line_total: Decimal | None = Field(default=None, ge=0)


class BusinessDocument(BaseModel):
    """两类采购单据的公共字段，而不是数据库记录本身。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    document_type: DocumentType
    document_number: str
    document_date: date | None = None
    purchase_order_number: str | None = None
    currency: str = Field(default="AUD", min_length=3, max_length=3)
    supplier: Party | None = None
    location: Party | None = None
    subtotal: Decimal | None = Field(default=None, ge=0)
    tax_total: Decimal | None = Field(default=None, ge=0)
    total: Decimal | None = Field(default=None, ge=0)
    items: list[LineItem] = Field(min_length=1)

    @model_validator(mode="after")
    def normalize_currency(self) -> BusinessDocument:
        """统一币种大小写，避免 AUD/aud 产生伪差异。"""

        self.currency = self.currency.upper()
        return self


class Invoice(BusinessDocument):
    """供应商要求付款的商业发票。"""

    document_type: DocumentType = DocumentType.INVOICE

    @model_validator(mode="after")
    def require_invoice_type(self) -> Invoice:
        """阻止 Receive Note Payload 被错误构造成 Invoice。"""

        if self.document_type != DocumentType.INVOICE:
            raise ValueError("Invoice document_type must be 'invoice'")
        return self


class ReceiveNote(BusinessDocument):
    """门店实际收货事实的记录，可多张共同对应一张发票。"""

    document_type: DocumentType = DocumentType.RECEIVE_NOTE

    @model_validator(mode="after")
    def require_receive_note_type(self) -> ReceiveNote:
        """阻止 Invoice Payload 被错误构造成 Receive Note。"""

        if self.document_type != DocumentType.RECEIVE_NOTE:
            raise ValueError("ReceiveNote document_type must be 'receive_note'")
        return self
