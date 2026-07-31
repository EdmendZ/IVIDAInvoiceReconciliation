"""持久化 MinerU 解析结果的领域记录。"""

from datetime import datetime

from pydantic import BaseModel, Field


class ParseResultRecord(BaseModel):
    """Run 对应的可复用解析文本和 MinIO Artifact 定位。"""

    parse_result_id: str
    run_id: str
    remote_job_id: str
    artifact_object_key: str
    markdown: str
    content_blocks: list[dict] = Field(default_factory=list)
    tables: list[dict] = Field(default_factory=list)
    page_count: int = Field(default=0, ge=0)
    created_at: datetime
