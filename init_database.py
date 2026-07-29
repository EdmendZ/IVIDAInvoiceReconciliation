import re

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings


def ensure_database_exists() -> str:
    settings = get_settings()
    database_url = make_url(settings.database_url)
    database_name = database_url.database
    if database_name is None or not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*",
        database_name,
    ):
        raise ValueError("DATABASE_URL must contain a safe PostgreSQL database name")

    maintenance_url = database_url.set(database="postgres")
    engine = create_engine(
        maintenance_url,
        isolation_level="AUTOCOMMIT",
        connect_args={
            "connect_timeout": settings.database_connect_timeout_seconds,
        },
    )
    try:
        with engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                {"database_name": database_name},
            ).scalar_one_or_none()
            if exists is None:
                connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    finally:
        engine.dispose()
    return database_name


if __name__ == "__main__":
    created_database = ensure_database_exists()
    command.upgrade(Config("alembic.ini"), "head")
    print(f"PostgreSQL database '{created_database}' and schema are up to date.")
