from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class WorkerHeartbeat(BaseModel):
    worker_id: str
    version: str
    started_at: datetime
    last_seen_at: datetime


class RuntimeStatus(BaseModel):
    api: Literal["up"] = "up"
    worker: Literal["online", "offline"]
    worker_last_seen_at: datetime | None = None
    worker_version: str | None = None
