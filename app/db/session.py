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


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
