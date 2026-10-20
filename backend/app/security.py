"""
Security building blocks, all in one place:

  1. Passwords   -> hashed with argon2 (we never store or log the real password)
  2. Login tokens -> signed JWTs, stored by the browser in an httpOnly cookie
  3. Secrets     -> PostHog API keys encrypted with Fernet before they go in the database
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import settings

# ----------------------------------------------------------------- passwords

_hasher = PasswordHasher()  # argon2id with safe defaults

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128

# Used to spend the same time on "unknown email" as on "wrong password", so an
# attacker can't tell from the response time which emails have accounts.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def verify_dummy_password(password: str) -> None:
    verify_password(_DUMMY_HASH, password)


def password_needs_rehash(password_hash: str) -> bool:
    """True if the hash was made with older/weaker settings (re-hash on next login)."""
    return _hasher.check_needs_rehash(password_hash)


def password_problem(password: str) -> str | None:
    """A friendly error message if a NEW password is not acceptable, else None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
    if password.strip() == "":
        return "Password can't be only spaces."
    return None


# ----------------------------------------------------------------- login tokens (JWT)

_ALGORITHM = "HS256"
SESSION_TOKEN = "session"
RESET_TOKEN = "reset"
RESET_TOKEN_MINUTES = 60
INVITE_DAYS = 7  # how long a "set your password" invitation link works
VIEWAS_TOKEN = "viewas"  # an admin looking at the dashboard as a client sees it
ADMIN_TOKEN = "admin"  # "this admin confirmed their password": opens the admin panel for a while


class TokenError(Exception):
    """The token is missing, expired, tampered with, or of the wrong type."""


def create_token(
    user_id: uuid.UUID, token_version: int, token_type: str, lifetime: timedelta, extra: dict[str, Any] | None = None
) -> str:
    """Make a signed token. Anyone can READ a JWT, so it holds only ids, never secrets.

    `ver` must match users.token_version. Bumping that number (password change or
    reset) makes every older token useless: that is how we "log out everywhere".
    """
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "ver": token_version,
        "typ": token_type,
        "iat": now,
        "exp": now + lifetime,
        **(extra or {}),
    }
    return jwt.encode(claims, _jwt_secret(), algorithm=_ALGORITHM)


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(
            token, _jwt_secret(), algorithms=[_ALGORITHM], options={"require": ["sub", "exp", "typ"]}
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    # A password-reset token must never work as a login cookie (and vice versa).
    if claims.get("typ") != expected_type:
        raise TokenError("wrong token type")
    return claims


def _jwt_secret() -> str:
    if not settings.jwt_secret:
        raise RuntimeError("JWT_SECRET is not set in backend/.env")
    return settings.jwt_secret


# ----------------------------------------------------------------- encrypting stored secrets


def _fernet() -> MultiFernet:
    """ENCRYPTION_KEY may hold several comma-separated keys (for key rotation):
    the FIRST one encrypts, ALL of them can decrypt."""
    if not settings.encryption_keys:
        raise RuntimeError("ENCRYPTION_KEY is not set in backend/.env")
    return MultiFernet([Fernet(key.encode()) for key in settings.encryption_keys])


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(encrypted: str) -> str:
    try:
        return _fernet().decrypt(encrypted.encode()).decode()
    except InvalidToken as exc:
        # Wrong/changed ENCRYPTION_KEY. Never include the encrypted value in the message.
        raise RuntimeError("Could not decrypt a stored secret: check ENCRYPTION_KEY") from exc


def generate_encryption_key() -> str:
    return Fernet.generate_key().decode()


def generate_jwt_secret() -> str:
    return secrets.token_urlsafe(48)
