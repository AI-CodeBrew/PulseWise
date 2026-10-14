"""Record important actions in the audit_log table ("who did what, when")."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def audit(
    db: Session,
    action: str,
    *,
    actor_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | uuid.UUID | None = None,
    ip: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an audit entry. It is saved together with the caller's next db.commit().

    Never put passwords, tokens or API keys in `details`.
    """
    db.add(
        AuditLog(
            actor_user_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            ip=ip,
            details=details,
        )
    )
