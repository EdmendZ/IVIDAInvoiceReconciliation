import logging
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.extraction_routes import router as extraction_router
from app.api.routes import diagnostic_router, router
from app.api.upload_routes import router as upload_router
from app.api.auth_routes import router as auth_router
from app.api.review_routes import router as review_router
from app.api.runtime_routes import router as runtime_router
from app.api.reconciliation_case_routes import router as reconciliation_case_router
from app.api.experiment_routes import router as experiment_router
from app.api.taptouch_integration_routes import router as taptouch_integration_router
from app.api.workspace_routes import (
    router as workspace_router,
    workspace_domain_exception_handler,
    workspace_http_exception_handler,
    workspace_validation_exception_handler,
)
from app.core.config import get_settings
from app.domain.workspace import WorkspaceError

settings = get_settings()
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Invoice and Receive Note extraction and reconciliation prototype",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def workspace_failure_boundary(request: Request, call_next):
    """Keep workspace infrastructure and unexpected failures safe and uniform."""

    try:
        return await call_next(request)
    except SQLAlchemyError as error:
        if not request.url.path.startswith("/api/workspace"):
            raise
        request_id = str(uuid4())
        logger.error(
            "Workspace database request failed",
            extra={
                "request_id": request_id,
                "exception_type": type(error).__name__,
            },
        )
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": "WORKSPACE_UNAVAILABLE",
                    "message": "工作台数据服务暂不可用，请稍后重试",
                }
            },
            headers={"X-Request-ID": request_id},
        )
    except Exception as error:
        if not request.url.path.startswith("/api/workspace"):
            raise
        request_id = str(uuid4())
        logger.error(
            "Unexpected workspace request failure",
            extra={
                "request_id": request_id,
                "exception_type": type(error).__name__,
            },
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": {
                    "code": "INTERNAL_ERROR",
                    "message": "工作台处理请求时发生内部错误",
                }
            },
            headers={"X-Request-ID": request_id},
        )


app.add_exception_handler(WorkspaceError, workspace_domain_exception_handler)
app.add_exception_handler(HTTPException, workspace_http_exception_handler)
app.add_exception_handler(StarletteHTTPException, workspace_http_exception_handler)
app.add_exception_handler(
    RequestValidationError,
    workspace_validation_exception_handler,
)
app.include_router(router)
app.include_router(upload_router)
app.include_router(extraction_router)
app.include_router(auth_router)
app.include_router(review_router)
app.include_router(runtime_router)
app.include_router(reconciliation_case_router)
app.include_router(experiment_router)
app.include_router(taptouch_integration_router)
app.include_router(workspace_router)
if settings.app_env.lower() == "dev":
    app.include_router(diagnostic_router)
