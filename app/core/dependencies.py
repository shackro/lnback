import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import require_secret_key
from app.db.session import get_db
from app.models import AdminUser

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
ADMIN_PERMISSIONS = {
    "dashboard.read",
    "inventory.manage",
    "holds.manage",
    "loans.manage",
    "inquiries.manage",
    "payouts.manage",
    "portfolio.manage",
    "settings.manage",
}


def require_admin(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> AdminUser:
    secret_key = require_secret_key()
    try:
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
    except jwt.InvalidTokenError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate admin credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

    email = payload.get("sub")
    if payload.get("role") not in {"admin", "super_admin"} or not isinstance(email, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate admin credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    admin = db.query(AdminUser).filter(
        AdminUser.email == email,
        AdminUser.role.in_(("admin", "super_admin")),
    ).first()
    if (
        admin is None
        or payload.get("role") != admin.role
        or type(payload.get("ver")) is not int
        or payload["ver"] != admin.token_version
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate admin credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return admin


def require_permission(permission: str):
    def check_permission(admin: AdminUser = Depends(require_admin)) -> AdminUser:
        if admin.role != "super_admin" and permission not in admin.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission}",
            )
        return admin

    return check_permission


def require_super_admin(admin: AdminUser = Depends(require_admin)) -> AdminUser:
    if admin.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the super administrator can manage administrator access",
        )
    return admin


require_portfolio_admin = require_permission("portfolio.manage")
