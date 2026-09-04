from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from finpulse.db import Base
from finpulse.enums import ExceptionStatus
from finpulse.models import ExceptionRow
from finpulse.review import approve_exception, escalate_exception


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_approve_marks_resolved_and_records_reviewer():
    db = _session()
    row = ExceptionRow(
        run_id="run-1",
        related_txn_ids="[]",
        detected_reason="NO_TRIPLE_MATCH",
        status=ExceptionStatus.NEEDS_REVIEW,
    )
    db.add(row)
    db.commit()
    approve_exception(db, row.id, "ada")
    db.refresh(row)
    assert row.status == ExceptionStatus.RESOLVED
    assert row.reviewer == "ada"
    assert row.reviewed_at is not None


def test_escalate_marks_unresolved():
    db = _session()
    row = ExceptionRow(
        run_id="run-1",
        related_txn_ids="[]",
        detected_reason="NO_TRIPLE_MATCH",
        status=ExceptionStatus.AUTO_SUGGESTED,
    )
    db.add(row)
    db.commit()
    escalate_exception(db, row.id, "ada", "still unclear")
    db.refresh(row)
    assert row.status == ExceptionStatus.UNRESOLVED
    assert row.reviewer == "ada"
