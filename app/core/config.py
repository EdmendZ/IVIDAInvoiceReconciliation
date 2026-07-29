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

    mongo_url: str = "mongodb://127.0.0.1:27017"
    mongo_db_name: str = "ivida_invoice_reconciliation"

    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "CHANGE_ME"
    minio_secret_key: str = "CHANGE_ME"
    minio_bucket_name: str = "ivida-invoice-documents"
    minio_secure: bool = False

    model_provider: str = "disabled"
    model_base_url: str = ""
    model_api_key: str = Field(default="", repr=False)
    model_name: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
