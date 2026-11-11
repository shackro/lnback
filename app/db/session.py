from collections.abc import Generator

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def sqlalchemy_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


database_url = sqlalchemy_database_url(settings.database_url)
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def ensure_product_media_columns(bind: Engine) -> None:
    columns = {column["name"] for column in inspect(bind).get_columns("products")}
    with bind.begin() as connection:
        if "images" not in columns:
            connection.execute(text("ALTER TABLE products ADD COLUMN images JSON NOT NULL DEFAULT '[]'"))
        if "inspection_video_url" not in columns:
            connection.execute(text("ALTER TABLE products ADD COLUMN inspection_video_url VARCHAR(2048)"))


def ensure_portfolio_audit_columns(bind: Engine) -> None:
    columns = {column["name"] for column in inspect(bind).get_columns("portfolio_loans")}
    if "offered_by" in columns:
        return
    with bind.begin() as connection:
        connection.execute(
            text("ALTER TABLE portfolio_loans ADD COLUMN offered_by VARCHAR(254) NOT NULL DEFAULT 'legacy'")
        )


def ensure_admin_security_columns(bind: Engine) -> None:
    columns = {column["name"] for column in inspect(bind).get_columns("admin_users")}
    missing_columns = {"permissions", "token_version"} - columns
    if not missing_columns:
        return
    with bind.begin() as connection:
        if "permissions" in missing_columns:
            connection.execute(text("ALTER TABLE admin_users ADD COLUMN permissions JSON NOT NULL DEFAULT '[]'"))
        if "token_version" in missing_columns:
            connection.execute(text("ALTER TABLE admin_users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
