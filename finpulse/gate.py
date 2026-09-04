from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path

from finpulse.config import ARTIFACT_DIR, FIXTURE_DIR
from finpulse.enums import ExceptionStatus, Source, WINDOW_HOURS, MATCH_RULE
from finpulse.matcher import TxnView, find_triples, leftover_groups, quantize, within_window


class AnomalyFamily(StrEnum):
    AMOUNT = "AMOUNT"
    DATE = "DATE"
    MISSING_SOURCE = "MISSING_SOURCE"
    DUPLICATE = "DUPLICATE"


REQUIRED_SOURCES = (Source.RAZORPAY, Source.BANK, Source.LEDGER)


def detect_families(txns: list[TxnView], window_hours: int = WINDOW_HOURS) -> frozenset[AnomalyFamily]:
    """Independent evidence axes for one order_ref. BANK_FEE is AMOUNT, not its own family."""
    if not txns:
        return frozenset()

    families: set[AnomalyFamily] = set()
    by_source: dict[str, list[TxnView]] = {}
    for txn in txns:
        by_source.setdefault(txn.source, []).append(txn)

    if any(src not in by_source for src in REQUIRED_SOURCES):
        families.add(AnomalyFamily.MISSING_SOURCE)

    if any(len(rows) > 1 for rows in by_source.values()):
        families.add(AnomalyFamily.DUPLICATE)

    amounts = {quantize(txn.amount) for txn in txns}
    if len(txns) >= 2 and len(amounts) > 1:
        families.add(AnomalyFamily.AMOUNT)

    if len(txns) >= 2:
        for i, a in enumerate(txns):
            for b in txns[i + 1 :]:
                if not within_window(a.txn_time, b.txn_time, window_hours):
                    families.add(AnomalyFamily.DATE)
                    break
            if AnomalyFamily.DATE in families:
                break

    return frozenset(families)


def apply_unique_cause_gate(
    proposed_status: ExceptionStatus | str,
    families: frozenset[AnomalyFamily] | set[AnomalyFamily],
) -> ExceptionStatus:
    """Status/routing only. Never changes exception_type or scores."""
    status = ExceptionStatus(proposed_status)
    if len(families) >= 2:
        return ExceptionStatus.UNRESOLVED
    return status


def simulate_gate_on_views(txns: list[TxnView]) -> list[dict]:
    """Per leftover order_ref: families and gated status. Does not touch LLM fields."""
    triples = find_triples(txns, window_hours=WINDOW_HOURS, match_rule=MATCH_RULE)
    leftovers = leftover_groups(txns, triples)
    by_order: dict[str, list[TxnView]] = {}
    for txn in txns:
        by_order.setdefault(txn.order_ref, []).append(txn)

    rows = []
    for group in leftovers:
        families = detect_families(by_order[group.order_ref])
        rows.append(
            {
                "order_ref": group.order_ref,
                "anomaly_families": sorted(f.value for f in families),
                "family_count": len(families),
                "would_block_auto_suggest": len(families) >= 2,
            }
        )
    return rows


def write_frozen_run_gate_simulation(
    scored_exceptions_path: Path | None = None,
    fixture_dir: Path | None = None,
    out_path: Path | None = None,
) -> Path:
    """Read-only routing simulation. Does not modify run_27da232e artifacts or accuracy."""
    from decimal import Decimal

    from finpulse.ingest import load_source_csv, parse_txn_time

    fixture_dir = fixture_dir or FIXTURE_DIR
    scored_exceptions_path = scored_exceptions_path or (
        ARTIFACT_DIR / "run_27da232e-53a9-4122-abaf-57ed6e10d6a2" / "exceptions.json"
    )
    out_path = out_path or (ARTIFACT_DIR / "gate_simulation_27da232e.json")

    raw_rows = []
    for name in ("razorpay.csv", "bank.csv", "ledger.csv"):
        raw_rows.extend(load_source_csv(fixture_dir / name))

    views = [
        TxnView(
            id=i,
            source=row["source"],
            source_txn_id=row["source_txn_id"],
            order_ref=row["order_ref"],
            amount=Decimal(row["amount"]),
            currency=row.get("currency") or "INR",
            txn_time=parse_txn_time(row["txn_time"]),
            status=row.get("status") or "",
            description=row.get("description") or "",
        )
        for i, row in enumerate(raw_rows, start=1)
    ]
    sim_rows = simulate_gate_on_views(views)

    scored = json.loads(scored_exceptions_path.read_text(encoding="utf-8"))
    scored_by_id = {row["id"]: row for row in scored}
    answer_key = json.loads((fixture_dir / "answer_key.json").read_text(encoding="utf-8"))
    gt_by_ref = {row["order_ref"]: row["ground_truth_type"] for row in answer_key["exceptions"]}

    leftovers_sorted = [r["order_ref"] for r in sim_rows]
    paired = []
    blocked = 0
    for idx, order_ref in enumerate(leftovers_sorted, start=1):
        scored_row = scored_by_id.get(idx, {})
        families = sim_rows[idx - 1]["anomaly_families"]
        policy_status = scored_row.get("status")
        gated = (
            apply_unique_cause_gate(policy_status, {AnomalyFamily(f) for f in families}).value
            if policy_status
            else None
        )
        if sim_rows[idx - 1]["would_block_auto_suggest"]:
            blocked += 1
        paired.append(
            {
                "exception_id": idx,
                "order_ref": order_ref,
                "ground_truth_type": gt_by_ref.get(order_ref),
                "baseline_exception_type": scored_row.get("exception_type"),
                "baseline_status": policy_status,
                "gated_status": gated,
                "anomaly_families": families,
                "ai_verdict_correct_unchanged": scored_row.get("ai_verdict_correct"),
            }
        )

    payload = {
        "kind": "unique_cause_gate_simulation",
        "not": "an updated AI exception-type accuracy score",
        "baseline_run_id": "27da232e-53a9-4122-abaf-57ed6e10d6a2",
        "official_ai_exception_accuracy_pct": 85.0,
        "official_ai_correct": 34,
        "official_ai_scored": 40,
        "leftovers_simulated": len(paired),
        "multi_family_blocked_from_auto_suggest": blocked,
        "rows": paired,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path

