from finpulse.enums import ExceptionStatus, ExceptionType
from finpulse.policy import apply_policy


def test_high_confidence_is_auto_suggested():
    status = apply_policy(
        confidence=0.85,
        insufficient_evidence=False,
        exception_type=ExceptionType.BANK_FEE,
    )
    assert status == ExceptionStatus.AUTO_SUGGESTED


def test_just_under_threshold_needs_review():
    status = apply_policy(
        confidence=0.849,
        insufficient_evidence=False,
        exception_type=ExceptionType.DATE_DRIFT,
    )
    assert status == ExceptionStatus.NEEDS_REVIEW


def test_insufficient_evidence_is_unresolved():
    status = apply_policy(
        confidence=0.99,
        insufficient_evidence=True,
        exception_type=ExceptionType.BANK_FEE,
    )
    assert status == ExceptionStatus.UNRESOLVED


def test_unresolvable_type_is_unresolved_even_at_high_confidence():
    status = apply_policy(
        confidence=0.95,
        insufficient_evidence=False,
        exception_type=ExceptionType.UNRESOLVABLE,
    )
    assert status == ExceptionStatus.UNRESOLVED


def test_missing_prediction_is_unresolved():
    assert (
        apply_policy(confidence=None, insufficient_evidence=False, exception_type=None)
        == ExceptionStatus.UNRESOLVED
    )
