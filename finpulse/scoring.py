from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from finpulse.enums import ExceptionType
from finpulse.matcher import Triple, TxnView


@dataclass(frozen=True)
class MatcherScore:
    planted_should_match: int
    matches_created: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    traps_correctly_refused: int
    traps_incorrectly_matched: int


def _triple_key_from_views(triple: Triple) -> tuple[str, str, str]:
    return (
        triple.razorpay.source_txn_id,
        triple.bank.source_txn_id,
        triple.ledger.source_txn_id,
    )


def score_matcher(triples: list[Triple], answer_key: dict) -> MatcherScore:
    planted = {
        (
            row["razorpay_source_txn_id"],
            row["bank_source_txn_id"],
            row["ledger_source_txn_id"],
        )
        for row in answer_key["should_match"]
    }
    created = {_triple_key_from_views(t) for t in triples}
    tp = planted & created
    fp = created - planted
    fn = planted - created

    precision = (len(tp) / len(created)) if created else 1.0
    recall = (len(tp) / len(planted)) if planted else 1.0

    matched_order_refs = {t.razorpay.order_ref for t in triples}
    trap_types = {
        ExceptionType.BANK_FEE,
        ExceptionType.MISSING_BANK_RECEIPT,
        ExceptionType.DATE_DRIFT,
        ExceptionType.AMOUNT_MISMATCH,
        ExceptionType.UNRESOLVABLE,
    }
    trap_refs = {
        row["order_ref"]
        for row in answer_key["exceptions"]
        if row["ground_truth_type"] in trap_types
    }
    traps_incorrect = trap_refs & matched_order_refs
    traps_refused = trap_refs - matched_order_refs

    return MatcherScore(
        planted_should_match=len(planted),
        matches_created=len(created),
        true_positives=len(tp),
        false_positives=len(fp),
        false_negatives=len(fn),
        precision=precision,
        recall=recall,
        traps_correctly_refused=len(traps_refused),
        traps_incorrectly_matched=len(traps_incorrect),
    )


def score_exceptions(predicted_types: list[tuple[str | None, str | None]]) -> dict:
    """predicted_types: list of (predicted exception_type, ground_truth_type)."""
    scored = [(p, g) for p, g in predicted_types if g]
    correct = sum(1 for p, g in scored if p == g)
    total = len(scored)
    pct = (correct / total * 100.0) if total else None
    return {
        "scored": total,
        "correct": correct,
        "exception_accuracy_pct": pct,
    }


def cash_position(
    triples: list[Triple],
    leftover_txns: list[TxnView],
    answer_key: dict | None = None,
) -> dict[str, Decimal]:
    matched = sum((t.razorpay.amount for t in triples), Decimal("0.00"))
    gt_by_ref = {}
    if answer_key:
        gt_by_ref = {row["order_ref"]: row["ground_truth_type"] for row in answer_key["exceptions"]}

    in_transit = Decimal("0.00")
    exceptional = Decimal("0.00")
    by_order: dict[str, list[TxnView]] = {}
    for txn in leftover_txns:
        by_order.setdefault(txn.order_ref, []).append(txn)

    for order_ref, group in by_order.items():
        rp_amt = sum((t.amount for t in group if t.source == "RAZORPAY"), Decimal("0.00"))
        if rp_amt == 0:
            rp_amt = max((t.amount for t in group), default=Decimal("0.00"))
        kind = gt_by_ref.get(order_ref)
        sources = {t.source for t in group}
        if kind == ExceptionType.MISSING_BANK_RECEIPT or (
            kind is None and "RAZORPAY" in sources and "LEDGER" in sources and "BANK" not in sources
        ):
            in_transit += rp_amt
        else:
            exceptional += rp_amt

    return {
        "cash_matched_amount": matched.quantize(Decimal("0.01")),
        "cash_in_transit_amount": in_transit.quantize(Decimal("0.01")),
        "cash_exception_amount": exceptional.quantize(Decimal("0.01")),
    }
