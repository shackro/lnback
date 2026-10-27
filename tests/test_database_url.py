from app.db.session import sqlalchemy_database_url


def test_postgres_urls_use_psycopg_driver() -> None:
    assert sqlalchemy_database_url("postgres://user:pass@host/db") == (
        "postgresql+psycopg://user:pass@host/db"
    )
    assert sqlalchemy_database_url("postgresql://user:pass@host/db") == (
        "postgresql+psycopg://user:pass@host/db"
    )


def test_non_postgres_database_url_is_unchanged() -> None:
    assert sqlalchemy_database_url("sqlite:///./repo_fier.db") == "sqlite:///./repo_fier.db"
