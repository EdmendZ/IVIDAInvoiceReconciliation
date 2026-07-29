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
    basename = Path(filename.replace("\\", "/")).name.strip()
    if not basename:
        raise DocumentValidationError("Filename is required")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", basename)
    return stem[:150]


def _detect_document_type(filename: str, data: bytes) -> str:
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

