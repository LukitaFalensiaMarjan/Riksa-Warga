from sqlalchemy.orm import Session

from app.models import AuditLog


def log_action(
    db: Session,
    *,
    actor_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | str | None = None,
    old: dict | None = None,
    new: dict | None = None,
    reason: str | None = None,
) -> AuditLog:
    """Tambah entri audit ke sesi. Commit dilakukan pemanggil bersama perubahan utamanya."""
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        old_value=old,
        new_value=new,
        reason=reason,
    )
    db.add(entry)
    return entry
