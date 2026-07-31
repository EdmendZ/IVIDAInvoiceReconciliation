from __future__ import annotations

"""Parser 输出到业务 Document 的归一化契约。"""

from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, Field

from app.domain.documents import BusinessDocument, DocumentType
from app.domain.parsing import ParseResult


class FieldEvidence(BaseModel):
    """一个业务字段与原文页码/文本/表格位置之间的证据映射。"""

    field_path: str
    value: str | None = None
    page: int | None = Field(default=None, ge=1)
    source_text: str
    block_id: str | None = None
    table_id: str | None = None
    row_index: int | None = Field(default=None, ge=0)
    confidence: Decimal | None = Field(default=None, ge=0, le=1)


class NormalizationResult(BaseModel):
    """规范化文档、Evidence、原始响应摘要和调用计量。"""

    document: BusinessDocument
    evidence: list[FieldEvidence] = Field(default_factory=list)
    raw_response: dict
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_aud: Decimal | None = Field(default=None, ge=0)


class NormalizationProvider(Protocol):
    """可替换文本模型或本地模型的归一化接口。"""

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def prompt_version(self) -> str: ...

    def normalize(
        self,
        *,
        document_type: DocumentType,
        parse_result: ParseResult,
    ) -> NormalizationResult:
        """把已经解析的文档转换为指定业务类型。"""
        ...
