"""Audit logging (MASTER BUILD PROMPT section 54) — every sensitive
administrative action (a full-sync trigger, user creation, a role or
active-status change) is recorded, never performed silently. Rows are
append-only: nothing here is ever updated or deleted."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.database.models.audit import AuditLog, User


def record_audit(
    db: Session,
    actor: User | None,
    action: str,
    *,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_email=actor.email if actor else None,
            actor_role=(actor.role.value if hasattr(actor.role, "value") else str(actor.role)) if actor else None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
    )
