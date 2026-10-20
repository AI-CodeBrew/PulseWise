"""
FastAPI dependencies for "who is asking?" and "may they see this website?".

Every analytics endpoint goes through get_website_config(). It is THE check that
keeps one client from ever seeing another client's data, and the tests in
tests/test_tenant_isolation.py prove it for every endpoint.
"""

import dataclasses
import logging
import time
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.access import find_website_access
from app.config import WebsiteConfig, settings
from app.db import get_db
from app.models import User, Website
from app.security import ADMIN_TOKEN, SESSION_TOKEN, VIEWAS_TOKEN, TokenError, create_token, decode_token, decrypt_secret

log = logging.getLogger(__name__)

SESSION_COOKIE = "portal_session"
VIEW_AS_COOKIE = "portal_view_as"
ADMIN_COOKIE = "portal_admin"  # set when an admin confirms their password: the admin panel is open while it is valid
ADMIN_COOKIE_PATH = "/api"  # only the API ever needs it
ADMIN_LOCKED_MESSAGE = "Please confirm your password to use the admin panel."

DbSession = Annotated[Session, Depends(get_db)]

# While an admin is "viewing as a client" the session is READ-ONLY: only these writes still work.
VIEW_AS_ALLOWED_WRITES = {"/api/auth/logout", "/api/auth/view-as/end"}


def client_ip(request: Request) -> str:
    # Behind a proxy (e.g. in production), run uvicorn with --proxy-headers so this
    # is the visitor's real IP and not the proxy's.
    return request.client.host if request.client else "unknown"


def get_current_user(request: Request, db: DbSession) -> User:
    """The logged-in user, from the httpOnly session cookie. 401 if not logged in."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Please log in.")
    try:
        claims = decode_token(token, SESSION_TOKEN)
        user_id = uuid.UUID(claims["sub"])
    except (TokenError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=401, detail="Your session has expired. Please log in again.") from exc

    user = db.get(User, user_id)
    # token_version check: a password change/reset invalidates all older sessions.
    if user is None or not user.is_active or user.token_version != claims.get("ver"):
        raise HTTPException(status_code=401, detail="Your session has expired. Please log in again.")

    # "View as client" (admins only): which client the admin is looking at, if any.
    request.state.view_as_client_id = _view_as_client_id(request, user)
    if (
        request.state.view_as_client_id is not None
        and request.method not in ("GET", "HEAD", "OPTIONS")
        and request.url.path not in VIEW_AS_ALLOWED_WRITES
    ):
        raise HTTPException(
            status_code=403, detail="You are viewing as a client (read-only). Exit the client view first."
        )
    return user


def _view_as_client_id(request: Request, user: User) -> uuid.UUID | None:
    if not user.is_admin:
        return None
    token = request.cookies.get(VIEW_AS_COOKIE)
    if not token:
        return None
    try:
        claims = decode_token(token, VIEWAS_TOKEN)
        if claims.get("sub") != str(user.id):  # a cookie that belongs to somebody else
            return None
        return uuid.UUID(claims["client_id"])
    except (TokenError, ValueError, KeyError):
        return None  # expired or garbage: just behave as the normal admin


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_view_as_client_id(request: Request, _user: CurrentUser) -> uuid.UUID | None:
    """The client an admin is viewing as, or None. (Depends on get_current_user, which sets it.)"""
    return request.state.view_as_client_id


ViewAsClientId = Annotated[uuid.UUID | None, Depends(get_view_as_client_id)]


def admin_unlock_claims(request: Request, user: User) -> dict | None:
    """The admin's "password confirmed" cookie, if it is valid for THIS admin right now. Otherwise None."""
    token = request.cookies.get(ADMIN_COOKIE)
    if not user.is_admin or not token:
        return None
    try:
        claims = decode_token(token, ADMIN_TOKEN)
    except TokenError:
        return None  # expired or garbage
    # Made for this very admin, and still valid: a password change bumps token_version and locks everything again.
    if claims.get("sub") != str(user.id) or claims.get("ver") != user.token_version:
        return None
    return claims


def set_admin_cookie(response: Response, user: User) -> None:
    lifetime = timedelta(minutes=settings.admin_unlock_minutes)
    response.set_cookie(
        ADMIN_COOKIE,
        create_token(user.id, user.token_version, ADMIN_TOKEN, lifetime),
        max_age=int(lifetime.total_seconds()),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",  # never sent along with a request that another website started
        path=ADMIN_COOKIE_PATH,
    )


def clear_admin_cookie(response: Response) -> None:
    response.delete_cookie(ADMIN_COOKIE, path=ADMIN_COOKIE_PATH, secure=settings.cookie_secure, httponly=True, samesite="strict")


def require_admin(request: Request, response: Response, user: CurrentUser) -> User:
    """For admin-only endpoints (the admin panel). Enforced here, in the backend.

    Being an admin is not enough: the admin must also have confirmed their password a short while ago
    ("unlock", see routers/auth.py), so someone who borrows a logged-in browser still can't open the panel.
    The answer when it is locked is 423, so the screen can ask for the password instead of showing an error.

    While an admin views the dashboard "as a client" they act as that client, so admin tools are off.
    """
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Only admins can do this.")
    if request.state.view_as_client_id is not None:
        raise HTTPException(status_code=403, detail="Exit the client view to use admin tools.")
    claims = admin_unlock_claims(request, user)
    if claims is None:
        raise HTTPException(status_code=423, detail=ADMIN_LOCKED_MESSAGE)
    # While the admin keeps working the panel stays open: renew the cookie once half of its time is gone.
    if claims["exp"] - time.time() < settings.admin_unlock_minutes * 60 / 2:
        set_admin_cookie(response, user)
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def get_website_config(
    website_id: uuid.UUID, user: CurrentUser, db: DbSession, view_as_client_id: ViewAsClientId
) -> WebsiteConfig:
    """Load the website from the URL, IF this user may see it.

    Not allowed and not existing give the SAME 404 answer, so nobody can find out
    which website ids exist by trying them.
    """
    access = find_website_access(db, user, website_id, view_as_client_id)
    if access is None:
        raise HTTPException(status_code=404, detail="Website not found.")
    if access.role != "admin" and access.client_status != "active":
        raise HTTPException(status_code=403, detail="This account is suspended. Please contact support.")

    try:
        return dataclasses.replace(config_from_website(access.website), role=access.role)
    except RuntimeError:
        log.error("Cannot decrypt the PostHog key of website %s (ENCRYPTION_KEY changed?)", access.website.id)
        raise HTTPException(
            status_code=500, detail="This website's analytics connection is misconfigured. Please contact support."
        ) from None


def config_from_website(website: Website) -> WebsiteConfig:
    """The PostHog connection of a website, with its API key DECRYPTED (the only place that happens).

    Raises RuntimeError if the key can't be decrypted (ENCRYPTION_KEY changed).
    """
    return WebsiteConfig(
        website_id=str(website.id),
        name=website.name,
        posthog_host=website.posthog_host,
        project_id=website.posthog_project_id,
        api_key=decrypt_secret(website.posthog_api_key_encrypted),
        client_id=str(website.client_id),
    )


def require_feature(feature: str) -> Callable[..., WebsiteConfig]:
    """A dependency that, on top of get_website_config, checks that the client's PLAN includes `feature`.

    Admins (not viewing as a client) always pass. A client without a plan is unrestricted.
    """
    from app.billing.service import FEATURES, has_feature

    def dependency(website: Annotated[WebsiteConfig, Depends(get_website_config)], db: DbSession) -> WebsiteConfig:
        if website.role != "admin" and not has_feature(db, uuid.UUID(website.client_id), feature):
            raise HTTPException(
                status_code=403,
                detail=f"Your plan doesn't include {FEATURES[feature]}. Please contact support to upgrade.",
            )
        return website

    return dependency
