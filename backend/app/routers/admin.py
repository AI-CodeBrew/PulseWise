"""
The admin API (everything under /api/admin). Only for admins: the check is applied to the WHOLE router
by `dependencies=[Depends(require_admin)]`, so a new endpoint added here can't forget it
(tests/test_admin.py proves it for every admin endpoint).

Rules for this file:
  - never return a decrypted or encrypted PostHog API key;
  - every change writes an audit_log entry (never containing secrets);
  - problems with the input answer 400/404/409 with a message the admin can act on.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import accounts
from app.audit import audit
from app.billing.service import BillingError, check_member_limit, check_website_limit
from app.cache import cache
from app.config import settings
from app.deps import VIEW_AS_COOKIE, AdminUser, DbSession, client_ip, config_from_website, require_admin
from app.models import Alert, AuditLog, Client, ClientMember, Invoice, User, Website
from app.params import CursorParam, LimitParam, decode_cursor, encode_cursor
from app.posthog_admin import InvalidPostHogHost, check_connection, validate_host
from app.posthog_client import AnalyticsError, PostHogClient
from app.emailer import email_configured
from app.security import VIEWAS_TOKEN, create_token, encrypt_secret, hash_password, password_problem
from app.services.health import website_health
from app.snippet import build_snippet, ingestion_host

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

Role = Literal["owner", "viewer"]


# ------------------------------------------------------------------ input shapes


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    contact_email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=4000)


class ClientPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=4000)
    status: Literal["active", "suspended"] | None = None
    currency: Literal["PKR", "USD"] | None = None  # can't be changed once the client has invoices


class ConfirmIn(BaseModel):
    confirm: str = Field(max_length=200)  # must equal the name of what is being deleted


class WebsiteIn(BaseModel):
    ignore_plan_limit: bool = False  # add it even though the client's plan allows fewer websites
    name: str = Field(min_length=1, max_length=200)
    domain: str | None = Field(default=None, max_length=255)
    posthog_host: str = Field(max_length=255)
    posthog_project_id: int = Field(gt=0, lt=10**12)
    posthog_org_id: str | None = Field(default=None, max_length=64)
    posthog_project_token: str | None = Field(default=None, max_length=100)
    posthog_api_key: str = Field(min_length=8, max_length=512)
    skip_check: bool = False  # only for emergencies: save without testing the key


class WebsitePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    domain: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    posthog_host: str | None = Field(default=None, max_length=255)
    posthog_project_id: int | None = Field(default=None, gt=0, lt=10**12)
    posthog_org_id: str | None = Field(default=None, max_length=64)
    posthog_project_token: str | None = Field(default=None, max_length=100)
    posthog_api_key: str | None = Field(default=None, min_length=8, max_length=512)  # to rotate the key
    skip_check: bool = False


class MemberIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(default="", max_length=200)
    role: Role = "viewer"
    ignore_plan_limit: bool = False  # add them even though the client's plan allows fewer people


class MemberPatch(BaseModel):
    role: Role


class UserPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None


class ViewAsIn(BaseModel):
    client_id: uuid.UUID


class OnboardIn(BaseModel):
    """Everything needed to give one customer a working login: who they are, their password, their PostHog keys."""

    email: str = Field(min_length=3, max_length=320)
    name: str = Field(default="", max_length=200)
    password: str = Field(min_length=1, max_length=1024)  # chosen by the admin; shown/sent to the user once
    business_name: str | None = Field(default=None, max_length=200)  # defaults to the person's name
    phone: str | None = Field(default=None, max_length=50)
    website_name: str = Field(min_length=1, max_length=200)
    domain: str | None = Field(default=None, max_length=255)
    posthog_host: str = Field(max_length=255)
    posthog_project_id: int = Field(gt=0, lt=10**12)
    posthog_org_id: str | None = Field(default=None, max_length=64)
    posthog_project_token: str | None = Field(default=None, max_length=100)
    posthog_api_key: str = Field(min_length=8, max_length=512)
    send_email: bool = True  # email the login details to the user
    skip_check: bool = False


# ------------------------------------------------------------------ small helpers


def _get_client(db: Session, client_id: uuid.UUID) -> Client:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found.")
    return client


def _get_website(db: Session, website_id: uuid.UUID) -> Website:
    website = db.get(Website, website_id)
    if website is None:
        raise HTTPException(status_code=404, detail="Website not found.")
    return website


def _get_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _client_email(value: str | None) -> str | None:
    value = _clean(value)
    if value is None:
        return None
    try:
        return accounts.normalize_email(value)
    except accounts.AccountError as exc:
        raise _bad_request(str(exc)) from None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def website_dict(website: Website) -> dict[str, Any]:
    """A website for the admin UI. The API key is NEVER included, only whether one is stored."""
    return {
        "id": str(website.id),
        "client_id": str(website.client_id),
        "name": website.name,
        "domain": website.domain,
        "posthog_host": website.posthog_host,
        "posthog_project_id": website.posthog_project_id,
        "posthog_org_id": website.posthog_org_id,
        "posthog_project_token": website.posthog_project_token,
        "has_api_key": bool(website.posthog_api_key_encrypted),
        "is_active": website.is_active,
        "created_at": _iso(website.created_at),
    }


def member_dict(member: ClientMember) -> dict[str, Any]:
    user = member.user
    return {
        "user_id": str(user.id),
        "email": user.email,
        "name": user.name,
        "role": member.role,
        "is_active": user.is_active,
        "last_login_at": _iso(user.last_login_at),
    }


def client_dict(client: Client) -> dict[str, Any]:
    return {
        "id": str(client.id),
        "name": client.name,
        "contact_email": client.contact_email,
        "phone": client.phone,
        "notes": client.notes,
        "status": client.status,
        "suspended_reason": client.suspended_reason,
        "currency": client.currency,
        "created_at": _iso(client.created_at),
    }


async def _verify_connection(host: str, project_id: int, api_key: str) -> dict[str, Any]:
    """Validate the host, then test the key against PostHog. Raises 400 with a helpful message."""
    try:
        host = validate_host(host)
    except InvalidPostHogHost as exc:
        raise _bad_request(str(exc)) from None
    result = await check_connection(host, project_id, api_key)
    if not result["ok"]:
        raise _bad_request(f"Could not connect to PostHog: {result['message']}")
    return result


# ------------------------------------------------------------------ overview


@router.get("/overview", summary="Counts for the admin home page")
def overview(db: DbSession):
    def count(query) -> int:
        return db.scalar(query) or 0

    recent = db.execute(
        select(AuditLog, User.email).outerjoin(User, User.id == AuditLog.actor_user_id).order_by(AuditLog.created_at.desc()).limit(8)
    ).all()
    return {
        "clients": {
            "total": count(select(func.count()).select_from(Client)),
            "active": count(select(func.count()).select_from(Client).where(Client.status == "active")),
            "suspended": count(select(func.count()).select_from(Client).where(Client.status == "suspended")),
        },
        "websites": count(select(func.count()).select_from(Website).where(Website.is_active.is_(True))),
        "open_alerts": count(select(func.count()).select_from(Alert).where(Alert.status == "open")),
        "users": count(select(func.count()).select_from(User).where(User.is_admin.is_(False))),
        "admins": count(select(func.count()).select_from(User).where(User.is_admin.is_(True))),
        "recent_activity": [_audit_dict(entry, email) for entry, email in recent],
    }


# ------------------------------------------------------------------ clients


@router.get("/clients", summary="All clients")
def list_clients(db: DbSession, q: Annotated[str | None, Query(max_length=100)] = None):
    website_counts = dict(db.execute(select(Website.client_id, func.count()).group_by(Website.client_id)).all())
    member_counts = dict(db.execute(select(ClientMember.client_id, func.count()).group_by(ClientMember.client_id)).all())
    query = select(Client).order_by(Client.name)
    if q:
        query = query.where(func.lower(Client.name).contains(q.strip().lower(), autoescape=True))
    return {
        "results": [
            {**client_dict(c), "websites": website_counts.get(c.id, 0), "members": member_counts.get(c.id, 0)}
            for c in db.scalars(query)
        ]
    }


@router.post("/clients", status_code=201, summary="Create a client")
def create_client(body: ClientIn, request: Request, admin: AdminUser, db: DbSession):
    client = Client(
        name=body.name.strip(),
        contact_email=_client_email(body.contact_email),
        phone=_clean(body.phone),
        notes=_clean(body.notes),
    )
    db.add(client)
    db.flush()
    audit(db, "admin.client_created", actor_id=admin.id, target_type="client", target_id=client.id, ip=client_ip(request),
          details={"name": client.name})
    db.commit()
    return client_dict(client)


@router.get("/clients/{client_id}", summary="One client with its websites and members")
def get_client(client_id: uuid.UUID, db: DbSession):
    client = _get_client(db, client_id)
    return {
        **client_dict(client),
        "websites": [website_dict(w) for w in sorted(client.websites, key=lambda w: w.name.lower())],
        "members": [member_dict(m) for m in sorted(client.members, key=lambda m: m.user.email)],
    }


@router.patch("/clients/{client_id}", summary="Edit a client (or suspend / re-activate it)")
def update_client(client_id: uuid.UUID, body: ClientPatch, request: Request, admin: AdminUser, db: DbSession):
    client = _get_client(db, client_id)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        client.name = changes["name"].strip()
    if "contact_email" in changes:
        client.contact_email = _client_email(changes["contact_email"])
    if "phone" in changes:
        client.phone = _clean(changes["phone"])
    if "notes" in changes:
        client.notes = _clean(changes["notes"])
    if "currency" in changes and changes["currency"] != client.currency:
        if db.scalar(select(Invoice.id).where(Invoice.client_id == client.id).limit(1)):
            raise HTTPException(status_code=409, detail="This client already has invoices, so its currency can't be changed.")
        client.currency = changes["currency"]
    if "status" in changes and changes["status"] != client.status:
        client.status = changes["status"]
        client.suspended_reason = "manual" if changes["status"] == "suspended" else None
    audit(db, "admin.client_updated", actor_id=admin.id, target_type="client", target_id=client.id, ip=client_ip(request),
          details={"fields": sorted(changes)})
    db.commit()
    return client_dict(client)


@router.delete("/clients/{client_id}", summary="Delete a client and everything under it")
def delete_client(client_id: uuid.UUID, body: ConfirmIn, request: Request, admin: AdminUser, db: DbSession):
    client = _get_client(db, client_id)
    if body.confirm != client.name:
        raise _bad_request("To delete this client, type its exact name to confirm.")
    if db.scalar(select(Invoice.id).where(Invoice.client_id == client.id).limit(1)):
        raise HTTPException(status_code=409, detail="This client has invoices, which must be kept for your records. Suspend the client instead.")
    audit(db, "admin.client_deleted", actor_id=admin.id, target_type="client", target_id=client.id, ip=client_ip(request),
          details={"name": client.name, "websites": len(client.websites), "members": len(client.members)})
    db.delete(client)
    db.commit()
    cache.clear()
    return {"ok": True}


# ------------------------------------------------------------------ websites


@router.post("/clients/{client_id}/websites", status_code=201, summary="Add a website (a PostHog project) to a client")
async def create_website(client_id: uuid.UUID, body: WebsiteIn, request: Request, admin: AdminUser, db: DbSession):
    client = _get_client(db, client_id)
    if not body.ignore_plan_limit:
        try:
            check_website_limit(db, client.id)
        except BillingError as exc:
            raise HTTPException(status_code=409, detail=f"{exc} Upgrade their plan, or add it anyway.") from None
    try:
        host = validate_host(body.posthog_host)
    except InvalidPostHogHost as exc:
        raise _bad_request(str(exc)) from None
    api_key = body.posthog_api_key.strip()
    token = _clean(body.posthog_project_token)
    if not body.skip_check:
        result = await _verify_connection(host, body.posthog_project_id, api_key)
        token = token or result.get("project_token")  # found automatically if the key may read project info
    website = Website(
        client_id=client.id,
        name=body.name.strip(),
        domain=_clean(body.domain),
        posthog_host=host,
        posthog_project_id=body.posthog_project_id,
        posthog_org_id=_clean(body.posthog_org_id),
        posthog_project_token=token,
        posthog_api_key_encrypted=encrypt_secret(api_key),  # stored encrypted, never in plain text
    )
    db.add(website)
    db.flush()
    audit(db, "admin.website_created", actor_id=admin.id, target_type="website", target_id=website.id, ip=client_ip(request),
          details={"client_id": str(client.id), "name": website.name, "project_id": website.posthog_project_id})
    db.commit()
    return website_dict(website)


@router.get("/websites/{website_id}", summary="One website (never includes the API key)")
def get_website(website_id: uuid.UUID, db: DbSession):
    website = _get_website(db, website_id)
    return {**website_dict(website), "client_name": website.client.name}


@router.patch("/websites/{website_id}", summary="Edit a website or its PostHog connection")
async def update_website(website_id: uuid.UUID, body: WebsitePatch, request: Request, admin: AdminUser, db: DbSession):
    website = _get_website(db, website_id)
    changes = body.model_dump(exclude_unset=True, exclude={"skip_check"})

    connection_changed = any(k in changes for k in ("posthog_host", "posthog_project_id", "posthog_api_key"))
    new_host = website.posthog_host
    if "posthog_host" in changes:
        try:
            new_host = validate_host(changes["posthog_host"])
        except InvalidPostHogHost as exc:
            raise _bad_request(str(exc)) from None
    new_project = changes.get("posthog_project_id", website.posthog_project_id)
    if connection_changed and not body.skip_check:
        # Test the NEW details with the new (or the stored) key before saving anything.
        try:
            api_key = changes["posthog_api_key"].strip() if "posthog_api_key" in changes else config_from_website(website).api_key
        except RuntimeError:
            raise _bad_request("The stored API key can't be decrypted (was ENCRYPTION_KEY changed?). Enter the key again.") from None
        result = await _verify_connection(new_host, new_project, api_key)
        if not website.posthog_project_token and not changes.get("posthog_project_token"):
            changes["posthog_project_token"] = result.get("project_token")

    if "name" in changes:
        website.name = changes["name"].strip()
    if "domain" in changes:
        website.domain = _clean(changes["domain"])
    if "is_active" in changes:
        website.is_active = changes["is_active"]
    if "posthog_org_id" in changes:
        website.posthog_org_id = _clean(changes["posthog_org_id"])
    if "posthog_project_token" in changes:
        website.posthog_project_token = _clean(changes["posthog_project_token"])
    website.posthog_host = new_host
    website.posthog_project_id = new_project
    if "posthog_api_key" in changes:
        website.posthog_api_key_encrypted = encrypt_secret(changes["posthog_api_key"].strip())
    if connection_changed:
        cache.clear()  # old cached numbers may belong to the previous project

    # Never log the key itself: only WHICH fields changed.
    audit(db, "admin.website_updated", actor_id=admin.id, target_type="website", target_id=website.id, ip=client_ip(request),
          details={"fields": sorted(changes), "key_rotated": "posthog_api_key" in changes})
    db.commit()
    return website_dict(website)


@router.delete("/websites/{website_id}", summary="Delete a website")
def delete_website(website_id: uuid.UUID, body: ConfirmIn, request: Request, admin: AdminUser, db: DbSession):
    website = _get_website(db, website_id)
    if body.confirm != website.name:
        raise _bad_request("To delete this website, type its exact name to confirm.")
    audit(db, "admin.website_deleted", actor_id=admin.id, target_type="website", target_id=website.id, ip=client_ip(request),
          details={"name": website.name, "client_id": str(website.client_id)})
    db.delete(website)
    db.commit()
    cache.clear()
    return {"ok": True}


@router.get("/websites/{website_id}/check", summary="Is data arriving? (connection test + events in the last 24h)")
async def check_website(website_id: uuid.UUID, db: DbSession):
    website = _get_website(db, website_id)
    try:
        config = config_from_website(website)
    except RuntimeError:
        return {"connection": {"ok": False, "message": "The stored API key can't be decrypted (was ENCRYPTION_KEY changed?)."},
                "health": None}
    ph = PostHogClient(config)
    try:
        health = await website_health(ph)
    except AnalyticsError as exc:
        reason = exc.upstream_detail or exc.message
        return {"connection": {"ok": False, "message": f"PostHog error ({exc.upstream_status or '?'}): {reason}"}, "health": None}
    return {"connection": {"ok": True, "message": "Connected."}, "health": health}


@router.get("/websites/{website_id}/snippet", summary="The tracking snippet to install on the client's website")
async def get_snippet(website_id: uuid.UUID, db: DbSession):
    website = _get_website(db, website_id)
    if not website.posthog_project_token:
        # Try to learn the public token from PostHog (works if the API key may read project info).
        try:
            result = await check_connection(website.posthog_host, website.posthog_project_id, config_from_website(website).api_key)
        except RuntimeError:
            result = {"ok": False}
        if result.get("ok") and result.get("project_token"):
            website.posthog_project_token = result["project_token"]
            db.commit()
    token = website.posthog_project_token
    return {
        "project_token": token,
        "api_host": ingestion_host(website.posthog_host),
        "snippet": build_snippet(token, website.posthog_host) if token else None,
        # When missing, the admin pastes it (PostHog > Settings > Project > "Project token", starts with phc_).
        "needs_token": token is None,
    }


# ------------------------------------------------------------------ members and users


@router.post("/clients/{client_id}/members", status_code=201, summary="Give a person access to a client")
def add_member(client_id: uuid.UUID, body: MemberIn, request: Request, background: BackgroundTasks, admin: AdminUser, db: DbSession):
    client = _get_client(db, client_id)
    try:
        user = accounts.find_user(db, body.email)
        created = user is None
        if created:
            user = accounts.create_user(db, body.email, body.name)
    except accounts.AccountError as exc:
        raise _bad_request(str(exc)) from None
    if db.get(ClientMember, (client.id, user.id)):
        raise HTTPException(status_code=409, detail=f"{user.email} already has access to {client.name}.")
    if not body.ignore_plan_limit:
        try:
            check_member_limit(db, client.id)
        except BillingError as exc:
            db.rollback()  # (a brand-new user created above is not kept)
            raise HTTPException(status_code=409, detail=f"{exc} Upgrade their plan, or add them anyway.") from None
    db.add(ClientMember(client_id=client.id, user_id=user.id, role=body.role))
    audit(db, "admin.member_added", actor_id=admin.id, target_type="user", target_id=user.id, ip=client_ip(request),
          details={"client_id": str(client.id), "role": body.role, "new_user": created})
    db.commit()

    # A NEW person gets an invitation link to choose their password. The link is shown to the admin
    # (to send over WhatsApp, say) and emailed when email is configured.
    link = None
    if created:
        link = accounts.invite_link(user)
        background.add_task(accounts.send_invite_email, user, link, client.name)
    return {"user_id": str(user.id), "email": user.email, "role": body.role, "new_user": created, "invite_link": link}


@router.patch("/clients/{client_id}/members/{user_id}", summary="Change a member's role")
def update_member(client_id: uuid.UUID, user_id: uuid.UUID, body: MemberPatch, request: Request, admin: AdminUser, db: DbSession):
    member = db.get(ClientMember, (client_id, user_id))
    if member is None:
        raise HTTPException(status_code=404, detail="That person is not a member of this client.")
    member.role = body.role
    audit(db, "admin.member_role_changed", actor_id=admin.id, target_type="user", target_id=user_id, ip=client_ip(request),
          details={"client_id": str(client_id), "role": body.role})
    db.commit()
    return member_dict(member)


@router.delete("/clients/{client_id}/members/{user_id}", summary="Remove a person's access to a client")
def remove_member(client_id: uuid.UUID, user_id: uuid.UUID, request: Request, admin: AdminUser, db: DbSession):
    member = db.get(ClientMember, (client_id, user_id))
    if member is None:
        raise HTTPException(status_code=404, detail="That person is not a member of this client.")
    db.delete(member)
    audit(db, "admin.member_removed", actor_id=admin.id, target_type="user", target_id=user_id, ip=client_ip(request),
          details={"client_id": str(client_id)})
    db.commit()
    return {"ok": True}


@router.post("/users", status_code=201, summary="Add a customer in one step: login + password + their PostHog keys")
async def onboard_user(body: OnboardIn, request: Request, background: BackgroundTasks, admin: AdminUser, db: DbSession):
    """Creates the client, the login (with the password the admin chose), and the website with its PostHog
    connection, then (optionally) emails the login details. Nothing is saved unless ALL of it is valid,
    including a live test of the PostHog key."""
    try:
        email = accounts.normalize_email(body.email)
    except accounts.AccountError as exc:
        raise _bad_request(str(exc)) from None
    if accounts.find_user(db, email):
        raise HTTPException(status_code=409, detail=f"{email} already has an account. Add their website from the client's page instead.")
    problem = password_problem(body.password)
    if problem:
        raise _bad_request(problem)
    try:
        host = validate_host(body.posthog_host)
    except InvalidPostHogHost as exc:
        raise _bad_request(str(exc)) from None
    api_key = body.posthog_api_key.strip()
    token = _clean(body.posthog_project_token)
    if not body.skip_check:
        result = await _verify_connection(host, body.posthog_project_id, api_key)
        token = token or result.get("project_token")

    name = _clean(body.name) or ""
    client = Client(name=_clean(body.business_name) or name or email, contact_email=email, phone=_clean(body.phone))
    db.add(client)
    db.flush()
    user = accounts.create_user(db, email, name)
    user.password_hash = hash_password(body.password)
    db.add(ClientMember(client_id=client.id, user_id=user.id, role="owner"))
    website = Website(
        client_id=client.id,
        name=body.website_name.strip(),
        domain=_clean(body.domain),
        posthog_host=host,
        posthog_project_id=body.posthog_project_id,
        posthog_org_id=_clean(body.posthog_org_id),
        posthog_project_token=token,
        posthog_api_key_encrypted=encrypt_secret(api_key),
    )
    db.add(website)
    db.flush()
    # Never log the password or the key: only that they were set.
    audit(db, "admin.customer_onboarded", actor_id=admin.id, target_type="user", target_id=user.id, ip=client_ip(request),
          details={"client_id": str(client.id), "website_id": str(website.id), "project_id": website.posthog_project_id,
                   "emailed": body.send_email})
    db.commit()

    emailed = False
    if body.send_email:
        emailed = email_configured()  # (when it isn't, the details are printed to the server log instead)
        background.add_task(accounts.send_login_email, user, body.password, client.name)
    return {
        "user_id": str(user.id),
        "client_id": str(client.id),
        "website_id": str(website.id),
        "email": user.email,
        "login_url": f"{settings.frontend_url}/login",
        "emailed": emailed,
        "token_found": token is not None,
    }


@router.post("/users/{user_id}/invite-link", summary="A fresh 'set your password' link for a user")
def new_invite_link(user_id: uuid.UUID, request: Request, admin: AdminUser, db: DbSession):
    user = _get_user(db, user_id)
    audit(db, "admin.invite_link_created", actor_id=admin.id, target_type="user", target_id=user.id, ip=client_ip(request))
    db.commit()
    return {"email": user.email, "invite_link": accounts.invite_link(user)}


@router.get("/users", summary="All users")
def list_users(db: DbSession, q: Annotated[str | None, Query(max_length=100)] = None):
    query = select(User).order_by(User.email).limit(500)
    if q:
        needle = q.strip().lower()
        query = query.where(func.lower(User.email).contains(needle, autoescape=True) | func.lower(User.name).contains(needle, autoescape=True))
    users = db.scalars(query).all()
    return {
        "results": [
            {
                "id": str(u.id),
                "email": u.email,
                "name": u.name,
                "is_admin": u.is_admin,
                "is_active": u.is_active,
                "last_login_at": _iso(u.last_login_at),
                "clients": [{"id": str(m.client_id), "name": m.client.name, "role": m.role} for m in u.memberships],
            }
            for u in users
        ]
    }


@router.patch("/users/{user_id}", summary="Rename or (de)activate a user")
def update_user(user_id: uuid.UUID, body: UserPatch, request: Request, admin: AdminUser, db: DbSession):
    user = _get_user(db, user_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("is_active") is False and user.id == admin.id:
        raise _bad_request("You can't deactivate your own account.")
    if "name" in changes:
        user.name = (changes["name"] or "").strip()
    if "is_active" in changes:
        user.is_active = changes["is_active"]
        if not user.is_active:
            user.token_version += 1  # logs them out everywhere right now
    audit(db, "admin.user_updated", actor_id=admin.id, target_type="user", target_id=user.id, ip=client_ip(request),
          details={"fields": sorted(changes)})
    db.commit()
    return {"id": str(user.id), "email": user.email, "name": user.name, "is_active": user.is_active}


# ------------------------------------------------------------------ view as client


@router.post("/view-as", summary="Look at the dashboard exactly as a client sees it (read-only)")
def view_as(body: ViewAsIn, request: Request, response: Response, admin: AdminUser, db: DbSession):
    client = _get_client(db, body.client_id)
    lifetime = timedelta(hours=2)
    token = create_token(admin.id, admin.token_version, VIEWAS_TOKEN, lifetime, extra={"client_id": str(client.id)})
    response.set_cookie(
        VIEW_AS_COOKIE, token, max_age=int(lifetime.total_seconds()), httponly=True,
        secure=settings.cookie_secure, samesite="lax", path="/",
    )
    audit(db, "admin.view_as_started", actor_id=admin.id, target_type="client", target_id=client.id, ip=client_ip(request))
    db.commit()
    first = db.scalars(
        select(Website).where(Website.client_id == client.id, Website.is_active.is_(True)).order_by(Website.name).limit(1)
    ).first()
    return {"client_id": str(client.id), "client_name": client.name, "website_id": str(first.id) if first else None}


# ------------------------------------------------------------------ audit log


def _audit_dict(entry: AuditLog, actor_email: str | None) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "created_at": _iso(entry.created_at),
        "actor": actor_email,
        "action": entry.action,
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "ip": entry.ip,
        "details": entry.details,
    }


@router.get("/audit", summary="The audit log: who did what, newest first")
def audit_log(
    db: DbSession,
    limit: LimitParam = 50,
    cursor: CursorParam = None,
    action: Annotated[str | None, Query(max_length=64, pattern=r"^[a-z_.]*$", description="only actions starting with this")] = None,
):
    query = select(AuditLog, User.email).outerjoin(User, User.id == AuditLog.actor_user_id).order_by(AuditLog.created_at.desc())
    # Newest first. Entries with the same timestamp are ordered by id, and the cursor holds BOTH,
    # so no entry is ever skipped or shown twice between pages.
    query = query.order_by(AuditLog.id.desc())
    position = decode_cursor(cursor)
    if position:
        try:
            at = datetime.fromisoformat(position["t"])
            last_id = uuid.UUID(position["i"])
        except (KeyError, ValueError):
            raise HTTPException(status_code=422, detail="Invalid cursor") from None
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        query = query.where((AuditLog.created_at < at) | ((AuditLog.created_at == at) & (AuditLog.id < last_id)))
    if action:
        query = query.where(AuditLog.action.startswith(action, autoescape=True))
    rows = db.execute(query.limit(limit + 1)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    last = rows[-1][0] if rows else None
    return {
        "results": [_audit_dict(entry, email) for entry, email in rows],
        "next_cursor": encode_cursor(t=last.created_at.isoformat(), i=str(last.id)) if has_more and last else None,
    }
