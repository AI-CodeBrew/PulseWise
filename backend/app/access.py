"""
Who may see which website.

The rule:
  - an ADMIN (you) may see every website, of every client;
  - anyone else may see a website only if they are a member (owner or viewer)
    of the client that owns it, and that client is not suspended.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models import Client, ClientMember, User, Website


@dataclass
class WebsiteAccess:
    website: Website
    client_status: str
    role: str  # "admin", "owner" or "viewer"


def find_website_access(
    db: Session, user: User, website_id: uuid.UUID, view_as_client_id: uuid.UUID | None = None
) -> WebsiteAccess | None:
    """The website plus this user's role on it, or None if they may not see it at all.

    One query: the website, its client's status, and the user's membership (if any).
    `view_as_client_id`: an admin who is looking at the dashboard "as a client" sees exactly what
    that client's owner sees: only that client's websites, and suspension applies.
    """
    row = db.execute(
        select(Website, Client.status, ClientMember.role)
        .join(Client, Client.id == Website.client_id)
        .outerjoin(
            ClientMember,
            and_(ClientMember.client_id == Website.client_id, ClientMember.user_id == user.id),
        )
        .where(Website.id == website_id, Website.is_active.is_(True))
    ).first()
    if row is None:
        return None
    website, client_status, role = row
    if user.is_admin and view_as_client_id is not None:
        return WebsiteAccess(website, client_status, "owner") if website.client_id == view_as_client_id else None
    if user.is_admin:
        return WebsiteAccess(website, client_status, "admin")
    if role is None:  # not a member of this client
        return None
    return WebsiteAccess(website, client_status, role)


def accessible_websites(db: Session, user: User, view_as_client_id: uuid.UUID | None = None) -> list[dict]:
    """Every website this user may see, for the website switcher. No secrets in here."""
    query = (
        select(Website, Client)
        .join(Client, Client.id == Website.client_id)
        .where(Website.is_active.is_(True))
        .order_by(Client.name, Website.name)
    )
    if user.is_admin and view_as_client_id is not None:
        rows = [(w, c, "owner") for w, c in db.execute(query.where(Client.id == view_as_client_id)).all()]
    elif user.is_admin:
        rows = [(w, c, "admin") for w, c in db.execute(query).all()]
    else:
        query = query.add_columns(ClientMember.role).join(
            ClientMember,
            and_(ClientMember.client_id == Client.id, ClientMember.user_id == user.id),
        )
        rows = db.execute(query).all()

    from app.billing.service import FEATURES, client_features  # (imported here to avoid a circular import)

    features: dict[uuid.UUID, dict[str, bool]] = {}
    out = []
    for website, client, role in rows:
        if client.id not in features:  # one plan lookup per client, not per website
            features[client.id] = {name: True for name in FEATURES} if role == "admin" else client_features(db, client.id)
        out.append(
            {
                "id": str(website.id),
                "name": website.name,
                "domain": website.domain,
                "client_id": str(client.id),
                "client_name": client.name,
                "client_status": client.status,
                "client_has_logo": client.logo_mime is not None,  # (the picture itself is fetched separately)
                "role": role,
                "features": features[client.id],  # which parts of the dashboard this client's plan includes
            }
        )
    return out
