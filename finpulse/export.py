from __future__ import annotations

import csv
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from finpulse.config import ARTIFACT_DIR
from finpulse.models import ExceptionRow, Match, RunMetrics, Transaction
from finpulse.scoring import score_exceptions


EXCEPTION_CSV_FIELDS = [
    "id",
    "run_id",
    "status",
    "exception_type",
    "ground_truth_type",
    "ai_verdict_correct",
    "confidence",
    "detected_reason",
    "ai_explanation",
    "recommended_action",
    "related_txn_ids",
    "reviewer",
    "reviewed_at",
    "investigated_at",
    "ground_truth_label",
]


def exception_dict(row: ExceptionRow) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "status": row.status,
        "exception_type": row.exception_type,
        "ground_truth_type": row.ground_truth_type,
        "ai_verdict_correct": row.ai_verdict_correct,
        "confidence": row.confidence,
        "detected_reason": row.detected_reason,
        "ai_explanation": row.ai_explanation,
        "recommended_action": row.recommended_action,
        "related_txn_ids": json.loads(row.related_txn_ids),
        "reviewer": row.reviewer,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "investigated_at": row.investigated_at.isoformat() if row.investigated_at else None,
        "ground_truth_label": row.ground_truth_label,
        "llm_raw_response": row.llm_raw_response,
    }


def apply_exception_scores(db: Session, run_id: str) -> dict:
    rows = db.query(ExceptionRow).filter(ExceptionRow.run_id == run_id).all()
    pairs = [(row.exception_type, row.ground_truth_type) for row in rows]
    result = score_exceptions(pairs)
    for row in rows:
        if row.ground_truth_type:
            row.ai_verdict_correct = row.exception_type == row.ground_truth_type
        else:
            row.ai_verdict_correct = None
    metrics = db.query(RunMetrics).filter(RunMetrics.run_id == run_id).one()
    metrics.exception_accuracy_pct = result["exception_accuracy_pct"]
    if metrics.started_at and metrics.finished_at is None:
        metrics.finished_at = datetime.utcnow()
    if metrics.started_at and metrics.finished_at:
        wall = (metrics.finished_at - metrics.started_at).total_seconds()
        if wall < 0:
            wall = metrics.wall_clock_seconds or 0
        if metrics.investigate_ms:
            # Prefer instrumented wall when we have it; datetime resolution can be 1s.
            instrumented = (metrics.wall_clock_seconds or 0) + (metrics.investigate_ms / 1000.0)
            if instrumented > 0:
                wall = instrumented
                metrics.wall_clock_seconds = wall
        if wall > 0 and metrics.records_processed:
            metrics.records_per_second = metrics.records_processed / wall
            metrics.records_per_minute = metrics.records_processed / wall * 60.0
    db.flush()
    return result


def _metrics_dict(row: RunMetrics) -> dict:
    def dec(v):
        if v is None:
            return None
        if isinstance(v, Decimal):
            return f"{v:.2f}"
        return v

    return {
        "run_id": row.run_id,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "records_processed": row.records_processed,
        "exceptions_created": row.exceptions_created,
        "wall_clock_seconds": row.wall_clock_seconds,
        "records_per_minute": row.records_per_minute,
        "records_per_second": row.records_per_second,
        "match_ms": row.match_ms,
        "investigate_ms": row.investigate_ms,
        "avg_llm_latency_ms": row.avg_llm_latency_ms,
        "matcher_precision": row.matcher_precision,
        "matcher_recall": row.matcher_recall,
        "exception_accuracy_pct": row.exception_accuracy_pct,
        "manual_baseline_minutes_assumed": row.manual_baseline_minutes_assumed,
        "manual_baseline_note": "ASSUMED 3 minutes per exception — not a measured number",
        "cash_matched_amount": dec(row.cash_matched_amount),
        "cash_in_transit_amount": dec(row.cash_in_transit_amount),
        "cash_exception_amount": dec(row.cash_exception_amount),
    }


def write_run_artifacts(db: Session, run_id: str) -> Path:
    out = ARTIFACT_DIR / f"run_{run_id}"
    out.mkdir(parents=True, exist_ok=True)

    exceptions = db.query(ExceptionRow).filter(ExceptionRow.run_id == run_id).order_by(ExceptionRow.id).all()
    matches = db.query(Match).filter(Match.run_id == run_id).order_by(Match.id).all()
    metrics = db.query(RunMetrics).filter(RunMetrics.run_id == run_id).one()
    txns = {t.id: t for t in db.query(Transaction).all()}

    dumps = [exception_dict(row) for row in exceptions]
    (out / "exceptions.json").write_text(json.dumps(dumps, indent=2), encoding="utf-8")

    with (out / "exceptions.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=EXCEPTION_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in dumps:
            flat = dict(row)
            flat["related_txn_ids"] = json.dumps(row["related_txn_ids"])
            writer.writerow({k: flat.get(k) for k in EXCEPTION_CSV_FIELDS})

    unresolved = [
        row
        for row in dumps
        if row["status"] in ("UNRESOLVED", "NEEDS_REVIEW") and row["reviewed_at"] is None
    ]
    with (out / "unresolved.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=EXCEPTION_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in unresolved:
            flat = dict(row)
            flat["related_txn_ids"] = json.dumps(row["related_txn_ids"])
            writer.writerow({k: flat.get(k) for k in EXCEPTION_CSV_FIELDS})

    incorrect = [row for row in dumps if row["ai_verdict_correct"] is False]
    with (out / "incorrect.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=EXCEPTION_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in incorrect:
            flat = dict(row)
            flat["related_txn_ids"] = json.dumps(row["related_txn_ids"])
            writer.writerow({k: flat.get(k) for k in EXCEPTION_CSV_FIELDS})

    def txn_brief(txn_id: int) -> dict | None:
        t = txns.get(txn_id)
        if t is None:
            return None
        return {
            "id": t.id,
            "source": t.source,
            "source_txn_id": t.source_txn_id,
            "order_ref": t.order_ref,
            "amount": f"{Decimal(t.amount):.2f}",
            "txn_time": t.txn_time.isoformat(),
        }

    recon = {
        "run_id": run_id,
        "matched_triples": [
            {
                "match_id": m.id,
                "order_ref": txns[m.razorpay_txn_id].order_ref if m.razorpay_txn_id in txns else None,
                "amount": f"{Decimal(txns[m.razorpay_txn_id].amount):.2f}" if m.razorpay_txn_id in txns else None,
                "razorpay": txn_brief(m.razorpay_txn_id),
                "bank": txn_brief(m.bank_txn_id),
                "ledger": txn_brief(m.ledger_txn_id),
                "ground_truth_should_match": m.ground_truth_should_match,
                "matcher_correct": m.matcher_correct,
            }
            for m in matches
        ],
        "unresolved_exceptions": unresolved,
        "incorrect_exception_types": incorrect,
        "cash_position": {
            "matched": _metrics_dict(metrics)["cash_matched_amount"],
            "in_transit": _metrics_dict(metrics)["cash_in_transit_amount"],
            "exceptional": _metrics_dict(metrics)["cash_exception_amount"],
        },
        "counts": {
            "records_processed": metrics.records_processed,
            "matches": len(matches),
            "exceptions": len(exceptions),
            "unresolved_or_open_review": len(unresolved),
            "incorrect_exception_types": len(incorrect),
        },
    }
    (out / "recon_report.json").write_text(json.dumps(recon, indent=2), encoding="utf-8")
    (out / "metrics.json").write_text(json.dumps(_metrics_dict(metrics), indent=2), encoding="utf-8")
    return out
