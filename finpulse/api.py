from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from finpulse.db import get_db, init_db
from finpulse.export import write_run_artifacts
from finpulse.models import AuditEvent, ExceptionRow, RunMetrics, Transaction
from finpulse.pipeline import generate, run_batch
from finpulse.review import approve_exception, escalate_exception


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="FINPULSE AI", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReviewRequest(BaseModel):
    reviewer: str
    reason: str = ""


def _exception_out(row: ExceptionRow) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "status": row.status,
        "exception_type": row.exception_type,
        "detected_reason": row.detected_reason,
        "confidence": row.confidence,
        "ai_explanation": row.ai_explanation,
        "recommended_action": row.recommended_action,
        "related_txn_ids": json.loads(row.related_txn_ids),
        "reviewer": row.reviewer,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "investigated_at": row.investigated_at.isoformat() if row.investigated_at else None,
        "ground_truth_type": row.ground_truth_type,
        "ground_truth_label": row.ground_truth_label,
        "ai_verdict_correct": row.ai_verdict_correct,
    }


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/generate")
def generate_endpoint():
    key = generate()
    return {
        "canonical_cases": key["canonical_cases"],
        "physical_rows": key["physical_rows"],
        "row_counts": key["row_counts"],
        "planted_should_match": key["planted_should_match"],
        "planted_exceptions": key["planted_exceptions"],
        "exception_type_counts": key["exception_type_counts"],
    }


@app.post("/runs")
def create_run(reset: bool = True, skip_llm: bool = False, force_investigate: bool = False):
    return run_batch(reset=reset, skip_llm=skip_llm, force_investigate=force_investigate)


@app.get("/exceptions")
def list_exceptions(run_id: str | None = None, db: Session = Depends(get_db)):
    q = db.query(ExceptionRow)
    if run_id:
        q = q.filter(ExceptionRow.run_id == run_id)
    return [_exception_out(row) for row in q.order_by(ExceptionRow.id).all()]


@app.get("/runs/latest")
def latest_run(db: Session = Depends(get_db)):
    row = db.query(RunMetrics).order_by(RunMetrics.started_at.desc()).first()
    if row is None:
        raise HTTPException(404, "no runs")
    from finpulse.export import _metrics_dict

    return _metrics_dict(row)


@app.get("/exceptions/export")
def export_exceptions(run_id: str | None = None, fmt: str = "json", db: Session = Depends(get_db)):
    if run_id is None:
        latest = db.query(RunMetrics).order_by(RunMetrics.started_at.desc()).first()
        if latest is None:
            raise HTTPException(404, "no runs")
        run_id = latest.run_id
    out = write_run_artifacts(db, run_id)
    if fmt == "csv":
        return FileResponse(out / "exceptions.csv", filename="exceptions.csv", media_type="text/csv")
    if fmt == "unresolved":
        return FileResponse(out / "unresolved.csv", filename="unresolved.csv", media_type="text/csv")
    return FileResponse(out / "exceptions.json", filename="exceptions.json", media_type="application/json")


@app.get("/exceptions/{exception_id}")
def get_exception(exception_id: int, db: Session = Depends(get_db)):
    row = db.query(ExceptionRow).filter(ExceptionRow.id == exception_id).one_or_none()
    if row is None:
        raise HTTPException(404, "exception not found")
    related_ids = json.loads(row.related_txn_ids)
    txns = db.query(Transaction).filter(Transaction.id.in_(related_ids)).all()
    order_refs = {t.order_ref for t in txns}
    context = []
    if order_refs:
        context = db.query(Transaction).filter(Transaction.order_ref.in_(order_refs)).all()
    audits = (
        db.query(AuditEvent)
        .filter(AuditEvent.entity_id.in_([str(row.id), row.run_id]))
        .order_by(AuditEvent.event_time)
        .all()
    )
    return {
        "exception": _exception_out(row),
        "records": [
            {
                "id": t.id,
                "source": t.source,
                "source_txn_id": t.source_txn_id,
                "order_ref": t.order_ref,
                "amount": f"{t.amount:.2f}",
                "txn_time": t.txn_time.isoformat(),
                "status": t.status,
                "description": t.description,
            }
            for t in context
        ],
        "audit": [
            {
                "event_time": a.event_time.isoformat(),
                "actor_type": a.actor_type,
                "action": a.action,
                "reason": a.reason,
                "before_state": a.before_state,
                "after_state": a.after_state,
            }
            for a in audits
        ],
    }


@app.post("/exceptions/{exception_id}/approve")
def approve(exception_id: int, body: ReviewRequest, db: Session = Depends(get_db)):
    row = db.query(ExceptionRow).filter(ExceptionRow.id == exception_id).one_or_none()
    if row is None:
        raise HTTPException(404, "exception not found")
    return _exception_out(approve_exception(db, exception_id, body.reviewer))


@app.post("/exceptions/{exception_id}/escalate")
def escalate(exception_id: int, body: ReviewRequest, db: Session = Depends(get_db)):
    row = db.query(ExceptionRow).filter(ExceptionRow.id == exception_id).one_or_none()
    if row is None:
        raise HTTPException(404, "exception not found")
    return _exception_out(escalate_exception(db, exception_id, body.reviewer, body.reason))
