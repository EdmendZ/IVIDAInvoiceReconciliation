import os
import socket

from app.api.dependencies import get_object_storage, get_task_repository
from app.core.config import get_settings
from app.infra.database import get_session_factory
from app.infra.mineru_parser import MinerUPrecisionParser
from app.infra.postgres_extraction_run_repository import (
    PostgresExtractionRunRepository,
)
from app.infra.postgres_parse_repository import PostgresParseResultRepository
from app.workers.extraction_worker import ExtractionWorker


def build_extraction_worker() -> ExtractionWorker:
    settings = get_settings()
    parser = MinerUPrecisionParser.create(
        token=settings.mineru_api_token,
        base_url=settings.mineru_base_url,
        model_name=settings.mineru_model,
        language=settings.mineru_language,
        timeout_seconds=settings.mineru_timeout_seconds,
    )
    session_factory = get_session_factory()
    return ExtractionWorker(
        parser=parser,
        storage=get_object_storage(),
        task_repository=get_task_repository(),
        run_repository=PostgresExtractionRunRepository(session_factory),
        parse_repository=PostgresParseResultRepository(session_factory),
        poll_interval_seconds=settings.mineru_poll_interval_seconds,
    )


if __name__ == "__main__":
    worker = build_extraction_worker()
    worker.run_forever(
        worker_id=f"{socket.gethostname()}-{os.getpid()}",
        idle_seconds=2,
    )
