from sqlalchemy.orm import Session

from app.core.dependencies import ADMIN_PERMISSIONS
from app.models import AdminAuditLog, AdminUser


def record_admin_event(
    db: Session,
    *,
    actor_email: str,
    action: str,
    target_admin_email: str,
    details: dict[str, object],
) -> None:
    db.add(
        AdminAuditLog(
            actor_email=actor_email,
            action=action,
            target_admin_email=target_admin_email,
            details=details,
        )
    )


def promote_genesis_admin(db: Session) -> AdminUser | None:
    if db.query(AdminUser).filter(AdminUser.role == "super_admin").first() is not None:
        return None

    admin = db.query(AdminUser).order_by(AdminUser.id.asc()).first()
    if admin is None:
        return None

    admin.role = "super_admin"
    admin.permissions = sorted(ADMIN_PERMISSIONS)
    record_admin_event(
        db,
        actor_email="system.bootstrap",
        action="genesis_super_admin_promoted",
        target_admin_email=admin.email,
        details={"reason": "first_existing_admin", "permissions": admin.permissions},
    )
    db.commit()
    return admin
