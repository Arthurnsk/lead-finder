from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import AuditLog


def audit(
    db: Session,
    action: str,
    *,
    org_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    entity: str = "",
    entity_id: object = "",
    data: dict | None = None,
    ip: str = "",
) -> None:
    """Append an audit record; caller commits together with the change it describes."""
    db.add(
        AuditLog(
            organization_id=org_id,
            user_id=user_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id or ""),
            data=data or {},
            ip=ip,
        )
    )
