"""
Login, logout, "who am I", and password management.

How login works:
  1. The browser POSTs email + password to /api/auth/login.
  2. We check the password against its argon2 hash.
  3. We set an httpOnly cookie holding a signed token (JavaScript can't read it,
     so an XSS bug can't steal it). The browser sends it back on every request.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.access import accessible_websites
from app.audit import audit
from app.billing.summary import support_info
from app.config import settings
from app.deps import SESSION_COOKIE, VIEW_AS_COOKIE, CurrentUser, DbSession, admin_unlock_claims, clear_admin_cookie, client_ip, set_admin_cookie
from app.emailer import send_email
from app.models import Client, User
from app.rate_limit import admin_unlock_failures, login_failures_by_account, login_failures_by_ip, reset_requests_by_ip
from app.security import (
    RESET_TOKEN,
    RESET_TOKEN_MINUTES,
    SESSION_TOKEN,
    TokenError,
    create_token,
    decode_token,
    hash_password,
    password_needs_rehash,
    password_problem,
    verify_dummy_password,
    verify_password,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

# Generous max lengths: they only stop absurdly large inputs.
_EMAIL = Field(min_length=1, max_length=320)
_PASSWORD = Field(min_length=1, max_length=1024)


class LoginIn(BaseModel):
    email: str = _EMAIL
    password: str = _PASSWORD


class AdminUnlockIn(BaseModel):
    password: str = _PASSWORD


class ForgotPasswordIn(BaseModel):
    email: str = _EMAIL


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=1, max_length=4096)
    new_password: str = _PASSWORD


class ChangePasswordIn(BaseModel):
    current_password: str = _PASSWORD
    new_password: str = _PASSWORD


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _set_session_cookie(response: Response, user: User) -> None:
    lifetime = timedelta(days=settings.session_days)
    token = create_token(user.id, user.token_version, SESSION_TOKEN, lifetime)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(lifetime.total_seconds()),
        httponly=True,  # JavaScript can't read it
        secure=settings.cookie_secure,  # HTTPS only (in production)
        samesite="lax",  # not sent with requests started by other websites
        path="/",
    )


def _me(db: DbSession, user: User, view_as_client_id: uuid.UUID | None = None, admin_unlocked: bool = False) -> dict:
    view_as = None
    if view_as_client_id is not None:
        client = db.get(Client, view_as_client_id)
        view_as = {"client_id": str(view_as_client_id), "client_name": client.name if client else "?"}
    return {
        "user": {"id": str(user.id), "email": user.email, "name": user.name, "is_admin": user.is_admin},
        # Admins only: have they confirmed their password for the admin panel (it locks itself after a while)?
        "admin_unlocked": admin_unlocked and user.is_admin,
        "websites": accessible_websites(db, user, view_as_client_id),
        # Set while an admin is looking at the dashboard exactly as a client sees it (read-only).
        "view_as": view_as,
        "support": support_info(db),  # WhatsApp / email for the "Help" button
    }


def _wait_message(seconds: int) -> str:
    minutes = max(1, round(seconds / 60))
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


@router.post("/login", summary="Log in (sets the session cookie)")
def login(body: LoginIn, request: Request, response: Response, db: DbSession):
    ip = client_ip(request)
    email = normalize_email(body.email)
    account_key = f"{ip}|{email}"

    wait = login_failures_by_account.retry_after(account_key) or login_failures_by_ip.retry_after(ip)
    if wait:
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Please try again in {_wait_message(wait)}.",
            headers={"Retry-After": str(wait)},
        )

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        verify_dummy_password(body.password)  # same response time as a wrong password
        ok = False
    else:
        ok = verify_password(user.password_hash, body.password) and user.is_active

    if not ok:
        login_failures_by_account.hit(account_key)
        login_failures_by_ip.hit(ip)
        audit(db, "auth.login_failed", actor_id=user.id if user else None, ip=ip, details={"email": email})
        db.commit()
        # Same message whether the email exists or not.
        raise HTTPException(status_code=401, detail="Wrong email or password.")

    login_failures_by_account.reset(account_key)
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.last_login_at = datetime.now(timezone.utc)
    audit(db, "auth.login", actor_id=user.id, ip=ip)
    db.commit()

    _set_session_cookie(response, user)
    return _me(db, user)


@router.post("/logout", summary="Log out (clears the session cookie)")
def logout(response: Response):
    for cookie in (SESSION_COOKIE, VIEW_AS_COOKIE):
        response.delete_cookie(cookie, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")
    clear_admin_cookie(response)
    return {"ok": True}


@router.get("/me", summary="The logged-in user and the websites they can see")
def me(request: Request, user: CurrentUser, db: DbSession):
    return _me(db, user, request.state.view_as_client_id, admin_unlocked=admin_unlock_claims(request, user) is not None)


@router.post("/admin-unlock", summary="Confirm your password to open the admin panel (admins)")
def admin_unlock(body: AdminUnlockIn, request: Request, response: Response, user: CurrentUser, db: DbSession):
    """Logging in is not enough for the admin panel: the admin types the password once more. It opens the panel for
    ADMIN_UNLOCK_MINUTES (renewed while it is used). Wrong passwords are limited like at login and written to the audit log."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Only admins can do this.")
    ip = client_ip(request)
    key = str(user.id)  # (per admin account: whoever holds a stolen session still has to guess the password)
    wait = admin_unlock_failures.retry_after(key)
    if wait:
        raise HTTPException(
            status_code=429,
            detail=f"Too many wrong passwords. Please try again in {_wait_message(wait)}.",
            headers={"Retry-After": str(wait)},
        )
    if not verify_password(user.password_hash, body.password):
        admin_unlock_failures.hit(key)
        audit(db, "auth.admin_unlock_failed", actor_id=user.id, ip=ip)
        db.commit()
        # (403, not 401: a wrong password here must not log the admin out of the whole site)
        raise HTTPException(status_code=403, detail="Wrong password.")
    admin_unlock_failures.reset(key)
    set_admin_cookie(response, user)
    audit(db, "auth.admin_unlocked", actor_id=user.id, ip=ip)
    db.commit()
    return _me(db, user, None, admin_unlocked=True)


@router.post("/admin-lock", summary="Close the admin panel again (the password is asked next time)")
def admin_lock(request: Request, response: Response, user: CurrentUser, db: DbSession):
    clear_admin_cookie(response)
    if user.is_admin:
        audit(db, "auth.admin_locked", actor_id=user.id, ip=client_ip(request))
        db.commit()
    return _me(db, user, request.state.view_as_client_id, admin_unlocked=False)


@router.post("/view-as/end", summary="Stop viewing the dashboard as a client (admins)")
def end_view_as(request: Request, response: Response, user: CurrentUser, db: DbSession):
    client_id = request.state.view_as_client_id
    response.delete_cookie(VIEW_AS_COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")
    if client_id is not None:
        audit(db, "admin.view_as_ended", actor_id=user.id, target_type="client", target_id=client_id, ip=client_ip(request))
        db.commit()
    return _me(db, user, None, admin_unlocked=admin_unlock_claims(request, user) is not None)


@router.post("/forgot-password", summary="Email a password-reset link")
def forgot_password(body: ForgotPasswordIn, request: Request, background: BackgroundTasks, db: DbSession):
    ip = client_ip(request)
    wait = reset_requests_by_ip.retry_after(ip)
    if wait:
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Please try again in {_wait_message(wait)}.",
            headers={"Retry-After": str(wait)},
        )
    reset_requests_by_ip.hit(ip)

    user = db.scalar(select(User).where(User.email == normalize_email(body.email)))
    if user is not None and user.is_active:
        token = create_token(user.id, user.token_version, RESET_TOKEN, timedelta(minutes=RESET_TOKEN_MINUTES))
        link = f"{settings.frontend_url}/reset-password?token={token}"
        # Sent in the background, so the response takes the same time whether or not
        # the email exists (otherwise the delay would reveal which emails have accounts).
        background.add_task(
            send_email,
            user.email,
            "Reset your password",
            f"Hi {user.name or 'there'},\n\n"
            f"Someone (hopefully you) asked to reset your password. Open this link to choose a new one:\n\n"
            f"{link}\n\n"
            f"The link works once and expires in {RESET_TOKEN_MINUTES} minutes.\n"
            f"If you didn't ask for this, you can ignore this email.\n",
        )
        audit(db, "auth.password_reset_requested", actor_id=user.id, ip=ip)
        db.commit()

    # Always the same answer, so this can't be used to find out who has an account.
    return {"ok": True, "message": "If an account exists for that email, we've sent a link to reset the password."}


@router.post("/reset-password", summary="Set a new password using the emailed link")
def reset_password(body: ResetPasswordIn, request: Request, db: DbSession):
    invalid = HTTPException(status_code=400, detail="This reset link is invalid or has expired. Please request a new one.")
    try:
        claims = decode_token(body.token, RESET_TOKEN)
        user = db.get(User, uuid.UUID(claims["sub"]))
    except (TokenError, ValueError, KeyError):
        raise invalid from None
    if user is None or not user.is_active or user.token_version != claims.get("ver"):
        raise invalid

    problem = password_problem(body.new_password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)

    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # makes this link single-use AND logs out every existing session
    audit(db, "auth.password_reset", actor_id=user.id, ip=client_ip(request))
    db.commit()
    return {"ok": True}


@router.post("/change-password", summary="Change your password (while logged in)")
def change_password(body: ChangePasswordIn, request: Request, response: Response, user: CurrentUser, db: DbSession):
    ip = client_ip(request)
    key = f"change-password|{user.id}"
    if login_failures_by_account.retry_after(key):
        raise HTTPException(status_code=429, detail="Too many wrong attempts. Please try again later.")

    if not verify_password(user.password_hash, body.current_password):
        login_failures_by_account.hit(key)
        raise HTTPException(status_code=400, detail="Your current password is not correct.")
    problem = password_problem(body.new_password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)

    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # logs out every OTHER session...
    audit(db, "auth.password_changed", actor_id=user.id, ip=ip)
    db.commit()
    _set_session_cookie(response, user)  # ...while keeping this one logged in
    return {"ok": True}
