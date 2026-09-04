from datetime import datetime, timedelta
from decimal import Decimal

from finpulse.enums import MATCH_RULE, WINDOW_HOURS
from finpulse.matcher import TxnView, find_triples, leftover_groups


def _t(
    id_: int,
    source: str,
    sid: str,
    ref: str,
    amount: str,
    ts: datetime,
    desc: str = "",
) -> TxnView:
    return TxnView(
        id=id_,
        source=source,
        source_txn_id=sid,
        order_ref=ref,
        amount=Decimal(amount),
        currency="INR",
        txn_time=ts,
        status="ok",
        description=desc,
    )


BASE = datetime(2026, 8, 10, 12, 0, 0)


def test_exact_triple_matches():
    txns = [
        _t(1, "RAZORPAY", "pay_a", "ORD-1", "1000.00", BASE),
        _t(2, "BANK", "utr_a", "ORD-1", "1000.00", BASE + timedelta(hours=3)),
        _t(3, "LEDGER", "je_a", "ORD-1", "1000.00", BASE + timedelta(hours=1)),
    ]
    triples = find_triples(txns, WINDOW_HOURS, MATCH_RULE)
    assert len(triples) == 1
    assert leftover_groups(txns, triples) == []


def test_date_drift_outside_24h_is_refused():
    txns = [
        _t(1, "RAZORPAY", "pay_a", "ORD-1", "1000.00", BASE),
        _t(2, "BANK", "utr_a", "ORD-1", "1000.00", BASE + timedelta(hours=36)),
        _t(3, "LEDGER", "je_a", "ORD-1", "1000.00", BASE + timedelta(hours=1)),
    ]
    triples = find_triples(txns, WINDOW_HOURS, MATCH_RULE)
    assert triples == []
    groups = leftover_groups(txns, triples)
    assert len(groups) == 1
    assert groups[0].detected_reason == "NO_TRIPLE_MATCH"


def test_bank_fee_amount_mismatch_is_refused():
    txns = [
        _t(1, "RAZORPAY", "pay_a", "ORD-1", "1000.00", BASE),
        _t(2, "BANK", "utr_a", "ORD-1", "980.00", BASE + timedelta(hours=2)),
        _t(3, "LEDGER", "je_a", "ORD-1", "1000.00", BASE + timedelta(hours=1)),
    ]
    assert find_triples(txns, WINDOW_HOURS, MATCH_RULE) == []


def test_ledger_amount_mismatch_is_refused():
    txns = [
        _t(1, "RAZORPAY", "pay_a", "ORD-1", "1000.00", BASE),
        _t(2, "BANK", "utr_a", "ORD-1", "1000.00", BASE + timedelta(hours=2)),
        _t(3, "LEDGER", "je_a", "ORD-1", "500.00", BASE + timedelta(hours=1)),
    ]
    assert find_triples(txns, WINDOW_HOURS, MATCH_RULE) == []


def test_missing_bank_cannot_form_triple():
    txns = [
        _t(1, "RAZORPAY", "pay_a", "ORD-1", "1000.00", BASE),
        _t(3, "LEDGER", "je_a", "ORD-1", "1000.00", BASE + timedelta(hours=1)),
    ]
    assert find_triples(txns, WINDOW_HOURS, MATCH_RULE) == []
    assert len(leftover_groups(txns, [])) == 1


def test_duplicate_bank_row_leaves_one_match_and_one_leftover():
    txns = [
        _t(1, "RAZORPAY", "pay_a", "ORD-1", "1000.00", BASE),
        _t(2, "BANK", "utr_primary", "ORD-1", "1000.00", BASE + timedelta(hours=2)),
        _t(3, "LEDGER", "je_a", "ORD-1", "1000.00", BASE + timedelta(hours=1)),
        _t(4, "BANK", "utr_dup", "ORD-1", "1000.00", BASE + timedelta(hours=2, minutes=12)),
    ]
    triples = find_triples(txns, WINDOW_HOURS, MATCH_RULE)
    assert len(triples) == 1
    assert triples[0].bank.source_txn_id == "utr_primary"
    groups = leftover_groups(txns, triples)
    assert len(groups) == 1
    assert [t.source_txn_id for t in groups[0].related] == ["utr_dup"]


def test_boundary_exactly_24h_still_matches():
    txns = [
        _t(1, "RAZORPAY", "pay_a", "ORD-1", "1000.00", BASE),
        _t(2, "BANK", "utr_a", "ORD-1", "1000.00", BASE + timedelta(hours=24)),
        _t(3, "LEDGER", "je_a", "ORD-1", "1000.00", BASE + timedelta(hours=24)),
    ]
    triples = find_triples(txns, WINDOW_HOURS, MATCH_RULE)
    assert len(triples) == 1


def test_just_over_24h_is_refused():
    txns = [
        _t(1, "RAZORPAY", "pay_a", "ORD-1", "1000.00", BASE),
        _t(2, "BANK", "utr_a", "ORD-1", "1000.00", BASE + timedelta(hours=24, seconds=1)),
        _t(3, "LEDGER", "je_a", "ORD-1", "1000.00", BASE),
    ]
    assert find_triples(txns, WINDOW_HOURS, MATCH_RULE) == []
