"""旧同步抽取 Provider Contract 与安全禁用实现。

当前真实链路由 AsyncDocumentParser + NormalizationProvider + Worker 组成；这里
保留给同步实现和未配置环境的明确失败行为。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.domain.documents import BusinessDocument, DocumentType


@dataclass(frozen=True)
class ExtractionProviderResult:
    """同步 Provider 一次返回的文档、原始响应和计量。"""

    raw_output: dict
    normalized_document: BusinessDocument
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_aud: Decimal | None = None


class ExtractionProvider(Protocol):
    """同步端到端抽取接口。"""

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def extract(
        self,
        *,
        document_type: DocumentType,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> ExtractionProviderResult: ...


class ExtractionProviderDisabled(RuntimeError):
    """未配置模型时的显式失败，防止生成伪造结果。"""

    pass


class DisabledExtractionProvider:
    """默认禁用 Provider；所有 extract 调用都快速失败。"""

    @property
    def provider_name(self) -> str:
        return "disabled"

    @property
    def model_name(self) -> str:
        return "disabled"

    def extract(
        self,
        *,
        document_type: DocumentType,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> ExtractionProviderResult:
        raise ExtractionProviderDisabled(
            "No extraction model is configured. Set MODEL_PROVIDER before extraction."
        )
