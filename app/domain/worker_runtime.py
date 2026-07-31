"""Worker 心跳记录与对 UI 暴露的最小运行状态。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class WorkerHeartbeat(BaseModel):
    """某个 Worker 最近一次声明存活的时间和版本。"""

    worker_id: str
    version: str
    started_at: datetime
    last_seen_at: datetime


class RuntimeStatus(BaseModel):
    """不暴露主机或凭据的运行状态响应。"""

    api: Literal["up"] = "up"
    worker: Literal["online", "offline"]
    worker_last_seen_at: datetime | None = None
    worker_version: str | None = None
