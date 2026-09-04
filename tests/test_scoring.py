from finpulse.enums import ExceptionType
from finpulse.scoring import score_exceptions, score_matcher
from finpulse.matcher import Triple, TxnView
from datetime import datetime
from decimal import Decimal


def _txn(sid: str, ref: str = "ORD-1") -> TxnView:
    return TxnView(
        id=hash(sid) % 10_000,
        source="RAZORPAY" if sid.startswith("pay") else "BANK" if sid.startswith("utr") else "LEDGER",
        source_txn_id=sid,
        order_ref=ref,
        amount=Decimal("100.00"),
        currency="INR",
        txn_time=datetime(2026, 8, 1),
        status="ok",
        description="",
    )


def test_exception_accuracy_is_strict_type_equality():
    result = score_exceptions(
        [
            (ExceptionType.BANK_FEE, ExceptionType.BANK_FEE),
            (ExceptionType.DATE_DRIFT, ExceptionType.AMOUNT_MISMATCH),
            (None, ExceptionType.UNRESOLVABLE),
        ]
    )
    assert result["scored"] == 3
    assert result["correct"] == 1
    assert result["exception_accuracy_pct"] == (1 / 3) * 100


def test_matcher_precision_recall_against_planted_key():
    rp, bk, ld = _txn("pay_a"), _txn("utr_a"), _txn("je_a")
    triple = Triple(razorpay=rp, bank=bk, ledger=ld, match_rule="x")
    key = {
        "should_match": [
            {
                "razorpay_source_txn_id": "pay_a",
                "bank_source_txn_id": "utr_a",
                "ledger_source_txn_id": "je_a",
            }
        ],
        "exceptions": [],
    }
    score = score_matcher([triple], key)
    assert score.precision == 1.0
    assert score.recall == 1.0
    assert score.true_positives == 1
