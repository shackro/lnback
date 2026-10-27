from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, status
from pwdlib import PasswordHash

from app.core.config import settings

password_hash = PasswordHash.recommended()


def require_secret_key() -> str:
    if len(settings.secret_key.encode("utf-8")) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Set SECRET_KEY to a random value of at least 32 bytes",
        )
    return settings.secret_key


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return password_hash.hash(password)


def create_access_token(email: str) -> str:
    secret_key = require_secret_key()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.admin_token_expire_minutes)
    return jwt.encode({"sub": email, "role": "admin", "exp": expires_at}, secret_key, algorithm="HS256")
