"""
User accounts: creating users, invitation links, email addresses.

Used by the admin API now, and by the "team members" feature in the client portal later.
Nobody ever receives or chooses a password through an admin: a new user gets a one-time
"set your password" link (the same mechanism as "forgot password").
"""

import re
import secrets
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.emailer import send_email
from app.models import User
from app.security import INVITE_DAYS, RESET_TOKEN, create_token, hash_password

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccountError(ValueError):
    """A problem with the input that is safe to show to the person who made the request."""


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if len(email) > 320 or not EMAIL_RE.match(email):
        raise AccountError(f"'{email[:80]}' doesn't look like an email address.")
    return email


def find_user(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalize_email(email)))


def create_user(db: Session, email: str, name: str = "", *, is_admin: bool = False) -> User:
    """A new user with a random, unknown password: they set their own through an invitation link."""
    user = User(
        email=normalize_email(email),
        name=name.strip()[:200],
        password_hash=hash_password(secrets.token_urlsafe(32)),
        is_admin=is_admin,
    )
    db.add(user)
    db.flush()
    return user


def invite_link(user: User) -> str:
    """One-time link where the user chooses their password. Valid for INVITE_DAYS days.

    Single use: choosing a password bumps user.token_version, which makes the link (and
    every older login) invalid. Works for new users and for "resend the link" alike.
    """
    token = create_token(user.id, user.token_version, RESET_TOKEN, timedelta(days=INVITE_DAYS))
    return f"{settings.frontend_url}/reset-password?token={token}&invite=1"


def send_invite_email(user: User, link: str, client_name: str, invited_by: str | None = None) -> None:
    who = f"{invited_by} has" if invited_by else "You have been"
    send_email(
        user.email,
        f"You've been invited to {client_name}'s analytics dashboard",
        f"Hi {user.name or 'there'},\n\n"
        f"{who} given you access to the website analytics dashboard for {client_name}.\n\n"
        f"Open this link to choose your password and log in:\n\n{link}\n\n"
        f"The link works once and expires in {INVITE_DAYS} days.\n",
    )


def send_login_email(user: User, password: str, client_name: str) -> None:
    """The login details an admin set up for a customer (the admin chose the password)."""
    send_email(
        user.email,
        f"Your {client_name} analytics dashboard login",
        f"Hi {user.name or 'there'},\n\n"
        f"Your website analytics dashboard is ready.\n\n"
        f"Log in here: {settings.frontend_url}/login\n"
        f"Email: {user.email}\n"
        f"Password: {password}\n\n"
        f"Please change your password after logging in (Account page).\n",
    )


def parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
