from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from finpulse.enums import ActorType, ExceptionStatus
from finpulse.ingest import write_audit
from finpulse.models import ExceptionRow


def approve_exception(db: Session, exception_id: int, reviewer: str) -> ExceptionRow:
    row = db.query(ExceptionRow).filter(ExceptionRow.id == exception_id).one()
    before = {"status": row.status, "reviewer": row.reviewer}
    row.status = ExceptionStatus.RESOLVED
    row.reviewer = reviewer
    row.reviewed_at = datetime.utcnow()
    write_audit(
        db,
        ActorType.HUMAN,
        "APPROVE",
        str(row.id),
        reason=f"Approved by {reviewer}",
        before_state=before,
        after_state={"status": row.status, "reviewer": reviewer},
    )
    db.flush()
    return row


def escalate_exception(db: Session, exception_id: int, reviewer: str, reason: str) -> ExceptionRow:
    row = db.query(ExceptionRow).filter(ExceptionRow.id == exception_id).one()
    before = {"status": row.status, "reviewer": row.reviewer}
    row.status = ExceptionStatus.UNRESOLVED
    row.reviewer = reviewer
    row.reviewed_at = datetime.utcnow()
    write_audit(
        db,
        ActorType.HUMAN,
        "ESCALATE",
        str(row.id),
        reason=reason or f"Escalated by {reviewer}",
        before_state=before,
        after_state={"status": row.status, "reviewer": reviewer},
    )
    db.flush()
    return row
