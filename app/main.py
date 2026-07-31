from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.extraction_routes import router as extraction_router
from app.api.routes import diagnostic_router, router
from app.api.upload_routes import router as upload_router
from app.api.auth_routes import router as auth_router
from app.api.review_routes import router as review_router
from app.api.runtime_routes import router as runtime_router
from app.core.config import get_settings

settings = get_settings()

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
app.include_router(router)
app.include_router(upload_router)
app.include_router(extraction_router)
app.include_router(auth_router)
app.include_router(review_router)
app.include_router(runtime_router)
if settings.app_env.lower() == "dev":
    app.include_router(diagnostic_router)
