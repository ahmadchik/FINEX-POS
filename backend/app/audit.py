import json

from sqlalchemy.orm import Session

from .models import AuditLog, User


def write_audit(
    db: Session,
    user: User | None,
    action: str,
    *,
    entity: str = "",
    entity_id: int | None = None,
    payload: dict | None = None,
    company_id: int | None = None,
) -> None:
    db.add(
        AuditLog(
            company_id=company_id if company_id is not None else (user.company_id if user else None),
            user_id=user.id if user else None,
            action=action[:80],
            entity=(entity or "")[:80],
            entity_id=entity_id,
            payload=json.dumps(payload or {}, ensure_ascii=False)[:4000],
        )
    )
