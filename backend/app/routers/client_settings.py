"""
A client's own settings (account owners): business name, logo, time zone, report language, weekly report switch,
and the team (who has access).

Everything here is scoped to ONE client, and only that client's owners (or an admin) may use it.
"""

import base64
import binascii
import uuid
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import accounts, whatsapp
from app.audit import audit
from app.billing.service import BillingError, check_member_limit, has_feature
from app.deps import CurrentUser, DbSession, ViewAsClientId, client_ip
from app.security import hash_password, password_problem
from app.models import Client, ClientMember, User
from app.routers.billing import owner_client

router = APIRouter(prefix="/api/clients/{client_id}", tags=["client settings"])

MAX_LOGO_BYTES = 300_000
COMMON_TIMEZONES = [
    "Asia/Karachi", "Asia/Dubai", "Asia/Riyadh", "Asia/Kolkata", "Asia/Dhaka", "Asia/Singapore",
    "Europe/London", "Europe/Berlin", "America/New_York", "America/Chicago", "America/Los_Angeles", "Australia/Sydney", "UTC",
]
Role = Literal["owner", "viewer"]


def _logo_type(data: bytes) -> str | None:
    """What kind of picture this REALLY is, by its first bytes (we never trust the file name or the browser's claim)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None  # SVG, GIF and everything else is refused (SVG can carry scripts)


def _settings_dict(client: Client) -> dict:
    return {
        "name": client.name, "timezone": client.timezone, "report_language": client.report_language,
        "weekly_report_enabled": client.weekly_report_enabled, "has_logo": client.logo_data is not None,
        "whatsapp_available": whatsapp.whatsapp_configured(),  # the section is hidden when WhatsApp isn't set up on the server
        "whatsapp_number": client.whatsapp_number, "whatsapp_reports_enabled": client.whatsapp_reports_enabled,
        "timezones": COMMON_TIMEZONES if client.timezone in COMMON_TIMEZONES else [client.timezone, *COMMON_TIMEZONES],
    }


class SettingsPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z_]+(/[A-Za-z_+\-0-9]+){0,2}$")
    report_language: Literal["en", "roman_ur", "ur"] | None = None
    weekly_report_enabled: bool | None = None
    whatsapp_number: str | None = Field(default=None, max_length=40)  # "" removes it
    whatsapp_reports_enabled: bool | None = None


class LogoIn(BaseModel):
    data: str = Field(max_length=int(MAX_LOGO_BYTES * 1.4))  # the picture, base64-encoded


@router.get("/settings", summary="The client's settings (account owners)")
def get_settings(client_id: uuid.UUID, user: CurrentUser, db: DbSession, view_as: ViewAsClientId):
    return _settings_dict(owner_client(db, user, client_id, view_as))


@router.patch("/settings", summary="Change the client's settings")
def update_settings(client_id: uuid.UUID, body: SettingsPatch, request: Request, user: CurrentUser, db: DbSession, view_as: ViewAsClientId):
    client = owner_client(db, user, client_id, view_as)
    changes = body.model_dump(exclude_unset=True)
    if "timezone" in changes:
        try:
            ZoneInfo(changes["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(status_code=400, detail="That time zone isn't known.") from None
    if "whatsapp_number" in changes:
        raw = (changes["whatsapp_number"] or "").strip()
        if raw:
            number = whatsapp.normalize_number(raw)
            if number is None:
                raise HTTPException(status_code=400, detail="Please enter the WhatsApp number with its country code, for example +92 300 1234567.")
            changes["whatsapp_number"] = number
        else:
            changes["whatsapp_number"] = None
            changes["whatsapp_reports_enabled"] = False
    if changes.get("whatsapp_reports_enabled") and not (changes.get("whatsapp_number") or client.whatsapp_number):
        raise HTTPException(status_code=400, detail="Add your WhatsApp number first.")
    for field, value in changes.items():
        setattr(client, field, value.strip() if isinstance(value, str) else value)
    audit(db, "client.settings_changed", actor_id=user.id, target_type="client", target_id=client.id, ip=client_ip(request), details={"fields": sorted(changes)})
    db.commit()
    return _settings_dict(client)


# ------------------------------------------------------------------ logo


@router.put("/logo", summary="Upload the client's logo (PNG, JPEG or WebP, up to 300 KB)")
def upload_logo(client_id: uuid.UUID, body: LogoIn, request: Request, user: CurrentUser, db: DbSession, view_as: ViewAsClientId):
    client = owner_client(db, user, client_id, view_as)
    payload = body.data.split(",", 1)[-1]  # accept a "data:image/png;base64,...." URL as well
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="That file couldn't be read as a picture.") from None
    if len(data) > MAX_LOGO_BYTES:
        raise HTTPException(status_code=400, detail=f"The logo is too big. Please use a file under {MAX_LOGO_BYTES // 1000} KB.")
    mime = _logo_type(data)
    if mime is None:
        raise HTTPException(status_code=400, detail="Please upload a PNG, JPEG or WebP picture.")
    client.logo_data, client.logo_mime = data, mime
    audit(db, "client.logo_changed", actor_id=user.id, target_type="client", target_id=client.id, ip=client_ip(request), details={"bytes": len(data)})
    db.commit()
    return {"ok": True, "has_logo": True}


@router.delete("/logo", summary="Remove the logo")
def delete_logo(client_id: uuid.UUID, user: CurrentUser, db: DbSession, view_as: ViewAsClientId):
    client = owner_client(db, user, client_id, view_as)
    client.logo_data = client.logo_mime = None
    db.commit()
    return {"ok": True, "has_logo": False}


def _active_member(db, client_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    member = db.get(ClientMember, (client_id, user_id))
    return member is not None and not member.suspended


@router.get("/logo", summary="The client's logo (any member of the client)")
def get_logo(client_id: uuid.UUID, user: CurrentUser, db: DbSession, view_as: ViewAsClientId):
    client = db.get(Client, client_id)
    allowed = client is not None and (
        (user.is_admin and (view_as is None or view_as == client_id)) or _active_member(db, client_id, user.id)
    )
    if not allowed or client is None or client.logo_data is None:
        raise HTTPException(status_code=404, detail="No logo.")
    return Response(
        content=client.logo_data,
        media_type=client.logo_mime or "application/octet-stream",
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",  # even if someone opens the file directly, nothing runs
        },
    )


# ------------------------------------------------------------------ team


class InviteIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(default="", max_length=200)
    role: Role = "viewer"
    # Optional. With a password the owner creates the login themselves and hands it over (no email needed).
    # Without one, a brand-new person gets a one-time "choose your password" link instead.
    password: str | None = Field(default=None, max_length=1024)


class MemberPatch(BaseModel):
    role: Role | None = None
    suspended: bool | None = None  # True = lock them out for now (they stay on the list), False = let them back in


class PasswordIn(BaseModel):
    password: str = Field(max_length=1024)


def _owner_count(db, client_id: uuid.UUID) -> int:
    """Owners who can actually use the account (a suspended owner doesn't count: the account must keep one active owner)."""
    return len(db.scalars(select(ClientMember.user_id).where(
        ClientMember.client_id == client_id, ClientMember.role == "owner", ClientMember.suspended.is_(False))).all())


def _is_last_active_owner(db, member: ClientMember) -> bool:
    return member.role == "owner" and not member.suspended and _owner_count(db, member.client_id) <= 1


def _can_set_password(db, member: ClientMember, you: User) -> bool:
    """An owner may set a password only for people who belong to THIS account and nowhere else (and aren't admins).
    Otherwise an owner could take over a login that also protects another business's data."""
    person = member.user
    if person.id == you.id or person.is_admin or not person.is_active:
        return False
    return len(db.scalars(select(ClientMember.client_id).where(ClientMember.user_id == person.id)).all()) == 1


def _team(db, client: Client, user: User) -> dict:
    from app.billing.service import plan_for_client

    plan = plan_for_client(db, client.id)
    members = db.scalars(select(ClientMember).where(ClientMember.client_id == client.id)).all()
    return {
        "members": [
            {"user_id": str(m.user_id), "email": m.user.email, "name": m.user.name, "role": m.role, "is_you": m.user_id == user.id,
             "suspended": m.suspended, "can_set_password": _can_set_password(db, m, user),
             "last_login_at": m.user.last_login_at.isoformat() if m.user.last_login_at else None}
            for m in sorted(members, key=lambda m: m.user.email)
        ],
        "max_members": plan.max_team_members if plan else None,
        "can_invite": has_feature(db, client.id, "team_members"),
    }


@router.get("/team", summary="Who has access to this client (account owners)")
def get_team(client_id: uuid.UUID, user: CurrentUser, db: DbSession, view_as: ViewAsClientId):
    return _team(db, owner_client(db, user, client_id, view_as), user)


@router.post("/team", status_code=201, summary="Give someone access (account owners)")
def invite(client_id: uuid.UUID, body: InviteIn, request: Request, background: BackgroundTasks, user: CurrentUser, db: DbSession, view_as: ViewAsClientId):
    client = owner_client(db, user, client_id, view_as)
    if not has_feature(db, client.id, "team_members"):
        raise HTTPException(status_code=403, detail="Your plan doesn't include Team members. Please contact support to upgrade.")
    try:
        check_member_limit(db, client.id)
    except BillingError as exc:
        raise HTTPException(status_code=409, detail=f"{exc} Please contact support to upgrade.") from None
    password = body.password if body.password else None
    if password is not None and (problem := password_problem(password)):
        raise HTTPException(status_code=400, detail=problem)
    try:
        person = accounts.find_user(db, body.email)
        created = person is None
        if created:
            person = accounts.create_user(db, body.email, body.name)
            if password is not None:
                person.password_hash = hash_password(password)  # the owner chose it: no "set your password" link is needed
    except accounts.AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if db.get(ClientMember, (client.id, person.id)):
        db.rollback()
        raise HTTPException(status_code=409, detail=f"{person.email} already has access.")
    db.add(ClientMember(client_id=client.id, user_id=person.id, role=body.role))
    audit(db, "client.member_added", actor_id=user.id, target_type="user", target_id=person.id, ip=client_ip(request),
          details={"client_id": str(client.id), "role": body.role, "new_user": created, "with_password": created and password is not None})
    db.commit()

    # SECURITY: a "set your password" link is only ever created for a brand-new account. For someone who already
    # has an account we never create one: with it, the person inviting could take that account over.
    # (And a password we were given is NEVER applied to an existing account, for the same reason.)
    password_set = created and password is not None
    link = accounts.invite_link(person) if created and not password_set else None
    if link:
        background.add_task(accounts.send_invite_email, person, link, client.name, user.name or user.email)
    return {"email": person.email, "role": body.role, "invite_link": link, "password_set": password_set, "new_account": created}


@router.patch("/team/{user_id}", summary="Change someone's role, or suspend / re-activate them (account owners)")
def change_member(client_id: uuid.UUID, user_id: uuid.UUID, body: MemberPatch, request: Request, user: CurrentUser, db: DbSession, view_as: ViewAsClientId):
    client = owner_client(db, user, client_id, view_as)
    member = db.get(ClientMember, (client.id, user_id))
    if member is None:
        raise HTTPException(status_code=404, detail="That person isn't on this account.")
    if body.role is None and body.suspended is None:
        raise HTTPException(status_code=422, detail="Nothing to change.")
    if body.suspended is True and user_id == user.id:
        raise HTTPException(status_code=409, detail="You can't suspend yourself.")
    if (body.suspended is True or (body.role is not None and body.role != "owner")) and _is_last_active_owner(db, member):
        raise HTTPException(status_code=409, detail="An account needs at least one active owner.")
    if body.role is not None:
        member.role = body.role
        audit(db, "client.member_role_changed", actor_id=user.id, target_type="user", target_id=user_id, ip=client_ip(request), details={"client_id": str(client.id), "role": body.role})
    if body.suspended is not None and body.suspended != member.suspended:
        member.suspended = body.suspended
        audit(db, "client.member_suspended" if body.suspended else "client.member_unsuspended", actor_id=user.id, target_type="user", target_id=user_id, ip=client_ip(request), details={"client_id": str(client.id)})
    db.commit()
    return _team(db, client, user)


@router.put("/team/{user_id}/password", summary="Set a new password for someone on this account (account owners)")
def set_member_password(client_id: uuid.UUID, user_id: uuid.UUID, body: PasswordIn, request: Request, user: CurrentUser, db: DbSession, view_as: ViewAsClientId):
    client = owner_client(db, user, client_id, view_as)
    member = db.get(ClientMember, (client.id, user_id))
    if member is None:
        raise HTTPException(status_code=404, detail="That person isn't on this account.")
    if not _can_set_password(db, member, user):
        raise HTTPException(status_code=409, detail="You can't set a password for this person (it is their own login: they can use \"Forgot your password?\" or the Account page).")
    if problem := password_problem(body.password):
        raise HTTPException(status_code=400, detail=problem)
    member.user.password_hash = hash_password(body.password)
    member.user.token_version += 1  # they are logged out everywhere and must use the new password
    audit(db, "client.member_password_set", actor_id=user.id, target_type="user", target_id=user_id, ip=client_ip(request), details={"client_id": str(client.id)})
    db.commit()
    return _team(db, client, user)


@router.delete("/team/{user_id}", summary="Remove someone's access (account owners)")
def remove_member(client_id: uuid.UUID, user_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession, view_as: ViewAsClientId):
    client = owner_client(db, user, client_id, view_as)
    member = db.get(ClientMember, (client.id, user_id))
    if member is None:
        raise HTTPException(status_code=404, detail="That person isn't on this account.")
    if _is_last_active_owner(db, member):
        raise HTTPException(status_code=409, detail="An account needs at least one active owner.")
    db.delete(member)
    audit(db, "client.member_removed", actor_id=user.id, target_type="user", target_id=user_id, ip=client_ip(request), details={"client_id": str(client.id)})
    db.commit()
    return _team(db, client, user)

