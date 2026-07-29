from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "IVIDA Invoice Reconciliation"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8200
    cors_origins: str = "http://localhost:5274"
    upload_max_bytes: int = 25 * 1024 * 1024

    database_url: str = (
        "postgresql+psycopg://postgres:CHANGE_ME@127.0.0.1:5432/"
        "ivida_invoice_reconciliation"
    )
    database_connect_timeout_seconds: int = 3

    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "CHANGE_ME"
    minio_secret_key: str = "CHANGE_ME"
    minio_bucket_name: str = "ivida-invoice-documents"
    minio_secure: bool = False

    model_provider: str = "disabled"
    model_base_url: str = ""
    model_api_key: str = Field(default="", repr=False)
    model_name: str = ""

    mineru_api_token: str = Field(default="", repr=False)
    mineru_base_url: str = "https://mineru.net/api/v4"
    mineru_model: str = "vlm"
    mineru_language: str = "en"
    mineru_timeout_seconds: int = Field(default=600, ge=30, le=3600)
    mineru_poll_interval_seconds: int = Field(default=5, ge=1, le=60)

    normalization_base_url: str = ""
    normalization_api_key: str = Field(default="", repr=False)
    normalization_model: str = ""
    normalization_timeout_seconds: int = Field(default=120, ge=10, le=600)
    normalization_input_cost_aud_per_million: float | None = Field(
        default=None,
        ge=0,
    )
    normalization_output_cost_aud_per_million: float | None = Field(
        default=None,
        ge=0,
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
