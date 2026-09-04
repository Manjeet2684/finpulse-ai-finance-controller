from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from finpulse.enums import ActorType, CURRENCY, ExceptionStatus, MATCH_RULE, WINDOW_HOURS
from finpulse.matcher import ExceptionGroup, Triple, TxnView, find_triples, leftover_groups
from finpulse.models import AuditEvent, ExceptionRow, Match, Transaction


def parse_txn_time(value: str) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def load_source_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def ingest_rows(db: Session, rows: list[dict]) -> list[Transaction]:
    created: list[Transaction] = []
    for row in rows:
        txn = Transaction(
            source=row["source"],
            source_txn_id=row["source_txn_id"],
            order_ref=row["order_ref"],
            amount=Decimal(row["amount"]),
            currency=row.get("currency") or CURRENCY,
            txn_time=parse_txn_time(row["txn_time"]),
            status=row.get("status") or "",
            description=row.get("description") or "",
        )
        db.add(txn)
        created.append(txn)
    db.flush()
    return created


def ingest_fixture_dir(db: Session, fixture_dir: Path) -> list[Transaction]:
    rows: list[dict] = []
    for name in ("razorpay.csv", "bank.csv", "ledger.csv"):
        rows.extend(load_source_csv(fixture_dir / name))
    return ingest_rows(db, rows)


def load_answer_key(fixture_dir: Path) -> dict:
    return json.loads((fixture_dir / "answer_key.json").read_text(encoding="utf-8"))


def to_views(txns: list[Transaction]) -> list[TxnView]:
    return [
        TxnView(
            id=txn.id,
            source=txn.source,
            source_txn_id=txn.source_txn_id,
            order_ref=txn.order_ref,
            amount=Decimal(txn.amount),
            currency=txn.currency,
            txn_time=txn.txn_time,
            status=txn.status,
            description=txn.description,
        )
        for txn in txns
    ]


def persist_matches(db: Session, run_id: str, triples: list[Triple], answer_key: dict) -> list[Match]:
    planted = {
        (
            row["razorpay_source_txn_id"],
            row["bank_source_txn_id"],
            row["ledger_source_txn_id"],
        )
        for row in answer_key["should_match"]
    }
    stored: list[Match] = []
    for triple in triples:
        key = (
            triple.razorpay.source_txn_id,
            triple.bank.source_txn_id,
            triple.ledger.source_txn_id,
        )
        should = key in planted
        row = Match(
            run_id=run_id,
            razorpay_txn_id=triple.razorpay.id,
            bank_txn_id=triple.bank.id,
            ledger_txn_id=triple.ledger.id,
            match_rule=triple.match_rule,
            ground_truth_should_match=should,
            matcher_correct=should,
        )
        db.add(row)
        stored.append(row)
    db.flush()
    return stored


def persist_exceptions(
    db: Session, run_id: str, groups: list[ExceptionGroup], answer_key: dict
) -> list[ExceptionRow]:
    gt = {row["order_ref"]: row for row in answer_key["exceptions"]}
    stored: list[ExceptionRow] = []
    for group in groups:
        meta = gt.get(group.order_ref, {})
        row = ExceptionRow(
            run_id=run_id,
            related_txn_ids=json.dumps([t.id for t in group.related]),
            detected_reason=group.detected_reason,
            exception_type=None,
            status=ExceptionStatus.NEEDS_REVIEW,
            ground_truth_label=meta.get("ground_truth_label"),
            ground_truth_type=meta.get("ground_truth_type"),
        )
        db.add(row)
        stored.append(row)
    db.flush()
    return stored


def write_audit(
    db: Session,
    actor_type: ActorType,
    action: str,
    entity_id: str,
    reason: str,
    before_state: dict | None = None,
    after_state: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        event_time=datetime.utcnow(),
        actor_type=actor_type,
        action=action,
        entity_id=entity_id,
        before_state=json.dumps(before_state) if before_state is not None else None,
        after_state=json.dumps(after_state) if after_state is not None else None,
        reason=reason,
    )
    db.add(event)
    db.flush()
    return event


def run_matcher(txns: list[Transaction]) -> tuple[list[Triple], list[ExceptionGroup]]:
    views = to_views(txns)
    triples = find_triples(views, window_hours=WINDOW_HOURS, match_rule=MATCH_RULE)
    groups = leftover_groups(views, triples)
    return triples, groups
