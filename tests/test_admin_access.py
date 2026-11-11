from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import AdminAuditLog, AdminUser, Base
from app.services.admin_access import promote_genesis_admin


def test_first_existing_admin_is_promoted_once_and_audited() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        original = AdminUser(
            email="original@example.test",
            hashed_password="original-password-hash",
            role="admin",
            permissions=[],
        )
        later = AdminUser(
            email="later@example.test",
            hashed_password="later-password-hash",
            role="admin",
            permissions=[],
        )
        db.add_all([original, later])
        db.flush()

        promoted = promote_genesis_admin(db)

        assert promoted is not None
        assert promoted.id == original.id
        assert promoted.role == "super_admin"
        assert "portfolio.manage" in promoted.permissions
        assert promoted.hashed_password == "original-password-hash"
        assert later.role == "admin"
        assert promote_genesis_admin(db) is None
        audit_events = db.query(AdminAuditLog).all()
        assert len(audit_events) == 1
        assert audit_events[0].actor_email == "system.bootstrap"
        assert audit_events[0].target_admin_email == original.email
    engine.dispose()
