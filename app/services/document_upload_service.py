"""上传原件的信任边界。

浏览器提供的文件名和 MIME 都不可信；服务使用文件签名重新识别格式，并确保
MinIO 写入与任务创建失败时不会留下无法追踪的孤立对象。
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.domain.documents import DocumentType
from app.domain.extraction_tasks import ExtractionStatus, ExtractionTask
from app.services.ports import ExtractionTaskRepository, ObjectStorage


class DocumentValidationError(ValueError):
    pass


class ExtractionTaskNotFound(LookupError):
    pass


_DOCUMENT_SIGNATURES: tuple[tuple[bytes, str, set[str]], ...] = (
    (b"%PDF", "application/pdf", {".pdf"}),
    (b"\x89PNG\r\n\x1a\n", "image/png", {".png"}),
    (b"\xff\xd8\xff", "image/jpeg", {".jpg", ".jpeg"}),
)


def _safe_filename(filename: str) -> str:
    """移除路径和危险字符；对象键不能直接使用客户端传入的路径。"""

    basename = Path(filename.replace("\\", "/")).name.strip()
    if not basename:
        raise DocumentValidationError("Filename is required")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", basename)
    return stem[:150]


def _detect_document_type(filename: str, data: bytes) -> str:
    """根据 Magic Bytes 识别内容，并拒绝扩展名伪装。"""

    extension = Path(filename).suffix.casefold()
    for signature, content_type, extensions in _DOCUMENT_SIGNATURES:
        if data.startswith(signature):
            if extension not in extensions:
                raise DocumentValidationError(
                    "File extension does not match its actual content"
                )
            return content_type
    raise DocumentValidationError("Only PDF, PNG, JPG and JPEG files are supported")


class DocumentUploadService:
    def __init__(
        self,
        storage: ObjectStorage,
        repository: ExtractionTaskRepository,
        max_bytes: int,
    ) -> None:
        self._storage = storage
        self._repository = repository
        self._max_bytes = max_bytes

    def upload(
        self,
        document_type: DocumentType,
        filename: str,
        data: bytes,
        purchase_order_hint: str | None = None,
    ) -> ExtractionTask:
        """验证并持久化一份原件，返回文件级的长期 Task。"""

        if not data:
            raise DocumentValidationError("Uploaded document is empty")
        if len(data) > self._max_bytes:
            raise DocumentValidationError(
                f"Document exceeds the {self._max_bytes}-byte upload limit"
            )

        safe_filename = _safe_filename(filename)
        detected_content_type = _detect_document_type(safe_filename, data)
        task_id = str(uuid4())
        checksum = hashlib.sha256(data).hexdigest()
        object_key = f"{document_type.value}/{task_id}/original/{safe_filename}"
        now = datetime.now(UTC)
        task = ExtractionTask(
            task_id=task_id,
            document_type=document_type,
            original_filename=safe_filename,
            content_type=detected_content_type,
            size_bytes=len(data),
            sha256=checksum,
            storage_bucket=self._storage.bucket_name,
            storage_object_key=object_key,
            purchase_order_hint=purchase_order_hint,
            status=ExtractionStatus.UPLOADED,
            created_at=now,
            updated_at=now,
        )

        # 先保存原件再创建数据库记录；若数据库失败，补偿删除对象，避免孤儿文件。
        self._storage.put(object_key, data, detected_content_type)
        try:
            self._repository.create(task)
        except Exception:
            self._storage.delete(object_key)
            raise
        return task

    def get_task(self, task_id: str) -> ExtractionTask:
        task = self._repository.get(task_id)
        if task is None:
            raise ExtractionTaskNotFound(task_id)
        return task

    def list_tasks(self, limit: int = 100) -> list[ExtractionTask]:
        return self._repository.list_recent(limit)
