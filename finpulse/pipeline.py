from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from time import perf_counter

from sqlalchemy.orm import Session

from finpulse.config import ARTIFACT_DIR, FIXTURE_DIR
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
from finpulse.models import RunMetrics
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
