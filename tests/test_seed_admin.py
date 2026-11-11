import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from typer.testing import CliRunner

import seed_admin
from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.models import AdminUser, Base


@pytest.mark.parametrize("arguments", [[], ["createsuperuser"]])
def test_createsuperuser_creates_admin_with_hashed_password(monkeypatch, arguments: list[str]) -> None:
    monkeypatch.setattr(settings, "secret_key", "test-only-secret-key-with-at-least-32-bytes")
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(seed_admin, "engine", test_engine)
    monkeypatch.setattr(seed_admin, "SessionLocal", testing_session)

    result = CliRunner().invoke(
        seed_admin.cli,
        arguments,
        input="ADMIN@example.test\ncorrect horse battery staple\ncorrect horse battery staple\n",
    )

    assert result.exit_code == 0, result.output
    assert "Initial super administrator created for admin@example.test." in result.output
    assert "correct horse battery staple" not in result.output
    with testing_session() as db:
        admin = db.query(AdminUser).filter(AdminUser.email == "admin@example.test").one()
        assert admin.role == "super_admin"
        assert "portfolio.manage" in admin.permissions
        assert admin.hashed_password != "correct horse battery staple"
        assert verify_password("correct horse battery staple", admin.hashed_password)
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def test_createsuperuser_refuses_to_create_a_second_account(monkeypatch) -> None:
    monkeypatch.setattr(settings, "secret_key", "test-only-secret-key-with-at-least-32-bytes")
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(seed_admin, "engine", test_engine)
    monkeypatch.setattr(seed_admin, "SessionLocal", testing_session)
    Base.metadata.create_all(bind=test_engine)
    with testing_session() as db:
        db.add(AdminUser(
            email="root@example.test",
            hashed_password=get_password_hash("correct horse battery staple"),
            role="super_admin",
            permissions=["dashboard.read"],
        ))
        db.commit()

    result = CliRunner().invoke(
        seed_admin.cli,
        ["createsuperuser", "--email", "new@example.test"],
        input="correct horse battery staple\ncorrect horse battery staple\n",
    )

    assert result.exit_code != 0
    assert "Initial super administrator already exists" in result.output
    with testing_session() as db:
        assert db.query(AdminUser).count() == 1
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def test_createsuperuser_rejects_weak_password(monkeypatch) -> None:
    monkeypatch.setattr(settings, "secret_key", "test-only-secret-key-with-at-least-32-bytes")

    result = CliRunner().invoke(
        seed_admin.cli,
        ["createsuperuser"],
        input="admin@example.test\nshort\nshort\n",
    )

    assert result.exit_code != 0
    assert "Invalid value:" in result.output
    assert "between 12 and 256" in result.output
