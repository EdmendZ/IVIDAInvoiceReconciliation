"""上传文件级 Task 的领域状态。

Task 代表“这份原件需要被处理”，不会因一次 Run 失败或重试而更换身份。
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.domain.documents import DocumentType


class ExtractionStatus(StrEnum):
    """文件级状态；比 Run 阶段更粗，用于列表和用户操作。"""

    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExtractionTask(BaseModel):
    """一份原件的不可变元数据与当前处理摘要。

    Task 是面向用户的文件级身份：同一原件重试多次仍是同一个 Task。它只保留
    粗粒度状态，具体模型、阶段、成本和错误由关联的 ExtractionRun 记录。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    task_id: str
    document_type: DocumentType
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    storage_bucket: str
    storage_object_key: str
    purchase_order_hint: str | None = None
    status: ExtractionStatus
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
