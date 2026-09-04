from datetime import datetime, timedelta
from decimal import Decimal

from finpulse.enums import ExceptionStatus, ExceptionType
from finpulse.gate import AnomalyFamily, apply_unique_cause_gate, detect_families
from finpulse.matcher import TxnView
from finpulse.policy import apply_policy

BASE = datetime(2026, 8, 10, 12, 0, 0)


def _t(id_: int, source: str, sid: str, ref: str, amount: str, ts: datetime) -> TxnView:
    return TxnView(
        id=id_,
        source=source,
        source_txn_id=sid,
        order_ref=ref,
        amount=Decimal(amount),
        currency="INR",
        txn_time=ts,
        status="ok",
        description="",
    )


def test_bank_fee_pattern_is_amount_family_only():
    txns = [
        _t(1, "RAZORPAY", "pay", "ORD-1", "1000.00", BASE),
        _t(2, "BANK", "utr", "ORD-1", "980.00", BASE + timedelta(hours=4)),
        _t(3, "LEDGER", "je", "ORD-1", "1000.00", BASE + timedelta(hours=1)),
    ]
    assert detect_families(txns) == frozenset({AnomalyFamily.AMOUNT})


def test_ledger_booking_miss_is_amount_family_only():
    txns = [
        _t(1, "RAZORPAY", "pay", "ORD-1", "4300.00", BASE),
        _t(2, "BANK", "utr", "ORD-1", "4300.00", BASE + timedelta(hours=3)),
        _t(3, "LEDGER", "je", "ORD-1", "3800.00", BASE + timedelta(hours=1)),
    ]
    assert detect_families(txns) == frozenset({AnomalyFamily.AMOUNT})


def test_date_drift_with_equal_amounts_is_date_family_only():
    txns = [
        _t(1, "RAZORPAY", "pay", "ORD-1", "1000.00", BASE),
        _t(2, "BANK", "utr", "ORD-1", "1000.00", BASE + timedelta(hours=36)),
        _t(3, "LEDGER", "je", "ORD-1", "1000.00", BASE + timedelta(hours=1)),
    ]
    assert detect_families(txns) == frozenset({AnomalyFamily.DATE})


def test_missing_bank_is_missing_source_only_when_amounts_and_dates_align():
    txns = [
        _t(1, "RAZORPAY", "pay", "ORD-1", "1000.00", BASE),
        _t(3, "LEDGER", "je", "ORD-1", "1000.00", BASE + timedelta(hours=1)),
    ]
    assert detect_families(txns) == frozenset({AnomalyFamily.MISSING_SOURCE})


def test_duplicate_bank_row_is_duplicate_family_only():
    txns = [
        _t(1, "RAZORPAY", "pay", "ORD-1", "1000.00", BASE),
        _t(2, "BANK", "utr1", "ORD-1", "1000.00", BASE + timedelta(hours=2)),
        _t(3, "LEDGER", "je", "ORD-1", "1000.00", BASE + timedelta(hours=1)),
        _t(4, "BANK", "utr2", "ORD-1", "1000.00", BASE + timedelta(hours=2, minutes=12)),
    ]
    assert detect_families(txns) == frozenset({AnomalyFamily.DUPLICATE})


def test_three_way_amount_and_date_conflict_is_two_families():
    txns = [
        _t(1, "RAZORPAY", "pay", "ORD-1", "38000.00", BASE),
        _t(2, "BANK", "utr", "ORD-1", "38037.00", BASE + timedelta(days=2, hours=5)),
        _t(3, "LEDGER", "je", "ORD-1", "37981.00", BASE + timedelta(days=1, hours=11)),
    ]
    assert detect_families(txns) == frozenset({AnomalyFamily.AMOUNT, AnomalyFamily.DATE})


def test_missing_source_plus_amount_conflict_is_two_families():
    txns = [
        _t(1, "RAZORPAY", "pay", "ORD-1", "1000.00", BASE),
        _t(3, "LEDGER", "je", "ORD-1", "700.00", BASE + timedelta(hours=1)),
    ]
    assert detect_families(txns) == frozenset({AnomalyFamily.MISSING_SOURCE, AnomalyFamily.AMOUNT})


def test_duplicate_plus_date_drift_is_two_families():
    txns = [
        _t(1, "RAZORPAY", "pay", "ORD-1", "1000.00", BASE),
        _t(2, "BANK", "utr1", "ORD-1", "1000.00", BASE + timedelta(hours=2)),
        _t(3, "LEDGER", "je", "ORD-1", "1000.00", BASE + timedelta(hours=1)),
        _t(4, "BANK", "utr2", "ORD-1", "1000.00", BASE + timedelta(days=4)),
    ]
    families = detect_families(txns)
    assert AnomalyFamily.DUPLICATE in families
    assert AnomalyFamily.DATE in families
    assert len(families) >= 2


def test_gate_blocks_auto_suggest_when_cause_is_not_unique():
    families = frozenset({AnomalyFamily.AMOUNT, AnomalyFamily.DATE})
    assert (
        apply_unique_cause_gate(ExceptionStatus.AUTO_SUGGESTED, families)
        == ExceptionStatus.UNRESOLVED
    )


def test_gate_does_not_rewrite_single_family_auto_suggest():
    families = frozenset({AnomalyFamily.AMOUNT})
    assert (
        apply_unique_cause_gate(ExceptionStatus.AUTO_SUGGESTED, families)
        == ExceptionStatus.AUTO_SUGGESTED
    )


def test_single_family_low_confidence_stays_needs_review():
    policy = apply_policy(
        confidence=0.70,
        insufficient_evidence=False,
        exception_type=ExceptionType.DATE_DRIFT,
    )
    assert policy == ExceptionStatus.NEEDS_REVIEW
    assert (
        apply_unique_cause_gate(policy, frozenset({AnomalyFamily.DATE}))
        == ExceptionStatus.NEEDS_REVIEW
    )


def test_multi_family_overrides_needs_review_to_unresolved():
    policy = apply_policy(
        confidence=0.70,
        insufficient_evidence=False,
        exception_type=ExceptionType.AMOUNT_MISMATCH,
    )
    assert policy == ExceptionStatus.NEEDS_REVIEW
    assert (
        apply_unique_cause_gate(policy, frozenset({AnomalyFamily.AMOUNT, AnomalyFamily.DATE}))
        == ExceptionStatus.UNRESOLVED
    )


def test_fixture_v1_multi_family_orders_are_exactly_planted_unresolvable():
    import json
    from decimal import Decimal

    from finpulse.config import FIXTURE_DIR
    from finpulse.gate import simulate_gate_on_views
    from finpulse.ingest import load_source_csv, parse_txn_time
    from finpulse.matcher import TxnView

    raw_rows = []
    for name in ("razorpay.csv", "bank.csv", "ledger.csv"):
        raw_rows.extend(load_source_csv(FIXTURE_DIR / name))
    views = [
        TxnView(
            id=i,
            source=row["source"],
            source_txn_id=row["source_txn_id"],
            order_ref=row["order_ref"],
            amount=Decimal(row["amount"]),
            currency="INR",
            txn_time=parse_txn_time(row["txn_time"]),
            status=row["status"],
            description=row["description"],
        )
        for i, row in enumerate(raw_rows, start=1)
    ]
    key = json.loads((FIXTURE_DIR / "answer_key.json").read_text(encoding="utf-8"))
    unresolvable = {row["order_ref"] for row in key["exceptions"] if row["ground_truth_type"] == "UNRESOLVABLE"}
    blocked = {row["order_ref"] for row in simulate_gate_on_views(views) if row["would_block_auto_suggest"]}
    assert blocked == unresolvable


def test_gate_does_not_change_exception_type():
    proposed_type = ExceptionType.AMOUNT_MISMATCH
    status = apply_unique_cause_gate(
        ExceptionStatus.AUTO_SUGGESTED,
        frozenset({AnomalyFamily.AMOUNT, AnomalyFamily.DATE}),
    )
    assert proposed_type == ExceptionType.AMOUNT_MISMATCH
    assert status == ExceptionStatus.UNRESOLVED
