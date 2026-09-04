from finpulse.enums import AUTO_SUGGEST_THRESHOLD, ExceptionStatus, ExceptionType


def apply_policy(
    *,
    confidence: float | None,
    insufficient_evidence: bool,
    exception_type: ExceptionType | str | None,
) -> ExceptionStatus:
    if insufficient_evidence or exception_type is None or confidence is None:
        return ExceptionStatus.UNRESOLVED
    kind = ExceptionType(exception_type)
    if kind == ExceptionType.UNRESOLVABLE:
        return ExceptionStatus.UNRESOLVED
    if confidence >= AUTO_SUGGEST_THRESHOLD:
        return ExceptionStatus.AUTO_SUGGESTED
    return ExceptionStatus.NEEDS_REVIEW
