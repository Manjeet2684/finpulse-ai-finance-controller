from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from time import perf_counter

from sqlalchemy.orm import Session

from finpulse.config import ARTIFACT_DIR, FIXTURE_DIR, get_settings
from finpulse.db import init_db, reset_db, session_scope
from finpulse.enums import (
    MANUAL_MINUTES_PER_EXCEPTION_ASSUMED,
    ActorType,
    MATCH_RULE,
    WINDOW_HOURS,
)
from finpulse.generator import generate_fixture
from finpulse.ingest import (
    ingest_fixture_dir,
    load_answer_key,
    persist_exceptions,
    persist_matches,
    run_matcher,
    write_audit,
)
from finpulse.investigate import run_investigation
from finpulse.export import apply_exception_scores, write_run_artifacts
from finpulse.models import ExceptionRow, RunMetrics
from finpulse.scoring import cash_position, score_matcher


def generate(out_dir: Path | None = None) -> dict:
    return generate_fixture(out_dir or FIXTURE_DIR)


def run_gate_a(fixture_dir: Path | None = None, reset: bool = True) -> dict:
    fixture_dir = fixture_dir or FIXTURE_DIR
    if not (fixture_dir / "answer_key.json").exists():
        generate_fixture(fixture_dir)

    init_db()
    if reset:
        reset_db()

    run_id = str(uuid.uuid4())
    started = datetime.utcnow()
    t0 = perf_counter()

    with session_scope() as db:
        summary = _run_ingest_and_match(db, run_id, fixture_dir, started, t0)

    _write_gate_a_artifacts(run_id, summary, fixture_dir)
    return summary


def _run_ingest_and_match(
    db: Session, run_id: str, fixture_dir: Path, started: datetime, t0: float
) -> dict:
    answer_key = load_answer_key(fixture_dir)
    txns = ingest_fixture_dir(db, fixture_dir)
    write_audit(
        db,
        ActorType.SYSTEM,
        "INGEST",
        run_id,
        f"Ingested {len(txns)} rows from {fixture_dir}",
        after_state={"records": len(txns)},
    )

    match_t0 = perf_counter()
    triples, groups = run_matcher(txns)
    match_ms = (perf_counter() - match_t0) * 1000

    persist_matches(db, run_id, triples, answer_key)
    persist_exceptions(db, run_id, groups, answer_key)
    write_audit(
        db,
        ActorType.SYSTEM,
        "MATCH",
        run_id,
        f"Matcher {MATCH_RULE} window={WINDOW_HOURS}h",
        after_state={"triples": len(triples), "exception_groups": len(groups)},
    )

    matcher_score = score_matcher(triples, answer_key)
    leftover_txns = [t for g in groups for t in g.related]
    cash = cash_position(triples, leftover_txns, answer_key)

    finished = datetime.utcnow()
    wall = perf_counter() - t0
    records = len(txns)
    rpm = (records / wall * 60) if wall else None
    rps = (records / wall) if wall else None

    metrics = RunMetrics(
        run_id=run_id,
        started_at=started,
        finished_at=finished,
        records_processed=records,
        exceptions_created=len(groups),
        wall_clock_seconds=wall,
        records_per_minute=rpm,
        records_per_second=rps,
        match_ms=match_ms,
        matcher_precision=matcher_score.precision,
        matcher_recall=matcher_score.recall,
        manual_baseline_minutes_assumed=len(groups) * MANUAL_MINUTES_PER_EXCEPTION_ASSUMED,
        cash_matched_amount=cash["cash_matched_amount"],
        cash_in_transit_amount=cash["cash_in_transit_amount"],
        cash_exception_amount=cash["cash_exception_amount"],
    )
    db.add(metrics)
    db.flush()

    by_source: dict[str, int] = {}
    for txn in txns:
        by_source[txn.source] = by_source.get(txn.source, 0) + 1

    leftover_refs = {g.order_ref for g in groups}
    gt_counts: dict[str, int] = {}
    for row in answer_key["exceptions"]:
        if row["order_ref"] in leftover_refs:
            key = row["ground_truth_type"]
            gt_counts[key] = gt_counts.get(key, 0) + 1
    unlabeled = sum(1 for g in groups if g.order_ref not in {row["order_ref"] for row in answer_key["exceptions"]})
    if unlabeled:
        gt_counts["UNLABELED"] = unlabeled

    return {
        "run_id": run_id,
        "canonical_cases": answer_key["canonical_cases"],
        "physical_rows": records,
        "row_counts": by_source,
        "matches_created": len(triples),
        "exceptions_created": len(groups),
        "matcher": matcher_score.__dict__,
        "cash_position": {k: str(v) for k, v in cash.items()},
        "exception_ground_truth_counts": gt_counts,
        "timing": {
            "wall_clock_seconds": wall,
            "match_ms": match_ms,
            "records_per_minute": rpm,
            "records_per_second": rps,
        },
        "match_rule": MATCH_RULE,
        "window_hours": WINDOW_HOURS,
    }


def _write_gate_a_artifacts(run_id: str, summary: dict, fixture_dir: Path) -> None:
    out = ARTIFACT_DIR / f"run_{run_id}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "gate_a_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    # Copy answer key next to the run so a judge can compare without regenerating.
    key = (fixture_dir / "answer_key.json").read_text(encoding="utf-8")
    (out / "answer_key.json").write_text(key, encoding="utf-8")


def _exception_snapshot(row: ExceptionRow) -> dict:
    return {
        "id": row.id,
        "status": row.status,
        "exception_type": row.exception_type,
        "ground_truth_type": row.ground_truth_type,
        "confidence": row.confidence,
        "ai_explanation": row.ai_explanation,
        "recommended_action": row.recommended_action,
        "detected_reason": row.detected_reason,
        "related_txn_ids": json.loads(row.related_txn_ids),
        "investigated_at": row.investigated_at.isoformat() if row.investigated_at else None,
    }


def run_batch(
    fixture_dir: Path | None = None,
    reset: bool = True,
    skip_llm: bool = False,
    force_investigate: bool = False,
) -> dict:
    summary = run_gate_a(fixture_dir=fixture_dir, reset=reset)
    if skip_llm:
        with session_scope() as db:
            write_run_artifacts(db, summary["run_id"])
        return summary
    return _finish_investigation(summary["run_id"], summary, force_investigate=force_investigate)


def resume_investigation(run_id: str | None = None, retry_failed: bool = True) -> dict:
    """Continue LLM investigation on an existing run without re-ingesting."""
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is missing. Put it in .env before investigation.")
    init_db()
    with session_scope() as db:
        if run_id is None:
            latest = db.query(RunMetrics).order_by(RunMetrics.started_at.desc()).first()
            if latest is None:
                raise RuntimeError("No run to resume.")
            run_id = latest.run_id
        if retry_failed:
            rows = (
                db.query(ExceptionRow)
                .filter(ExceptionRow.run_id == run_id, ExceptionRow.exception_type.is_(None))
                .all()
            )
            for row in rows:
                row.investigated_at = None
        summary = {"run_id": run_id, "resumed": True}
    return _finish_investigation(run_id, summary, force_investigate=False)


def _finish_investigation(run_id: str, summary: dict, force_investigate: bool = False) -> dict:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is missing. Put it in .env before investigation.")

    t0 = perf_counter()
    with session_scope() as db:
        inv = run_investigation(db, run_id, force=force_investigate)
        investigate_ms = (perf_counter() - t0) * 1000
        rows = db.query(ExceptionRow).filter(ExceptionRow.run_id == run_id).all()
        status_counts: dict[str, int] = {}
        type_counts: dict[str, int] = {}
        for row in rows:
            status_counts[row.status] = status_counts.get(row.status, 0) + 1
            key = row.exception_type or "NONE"
            type_counts[key] = type_counts.get(key, 0) + 1
        unresolved = [_exception_snapshot(r) for r in rows if r.status == "UNRESOLVED"]
        metrics = db.query(RunMetrics).filter(RunMetrics.run_id == run_id).one()
        prev_ms = metrics.investigate_ms or 0.0
        metrics.investigate_ms = prev_ms + investigate_ms
        if inv["avg_llm_latency_ms"] is not None:
            metrics.avg_llm_latency_ms = inv["avg_llm_latency_ms"]
        metrics.finished_at = datetime.utcnow()
        score = apply_exception_scores(db, run_id)
        artifact_dir = write_run_artifacts(db, run_id)

    summary["investigation"] = {
        "investigated": inv["investigated"],
        "failed": inv["failed"],
        "retried": inv["retried"],
        "avg_llm_latency_ms": inv["avg_llm_latency_ms"],
        "investigate_ms": investigate_ms,
        "status_counts": status_counts,
        "predicted_type_counts": type_counts,
        "unresolved_examples": unresolved[:5],
        "unresolved_count": len(unresolved),
        "exception_accuracy": score,
        "artifact_dir": str(artifact_dir),
    }
    out = ARTIFACT_DIR / f"run_{run_id}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "gate_b_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary

