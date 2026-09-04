from pydantic import BaseModel, Field

from finpulse.enums import ExceptionType


class InvestigationResult(BaseModel):
    exception_type: ExceptionType
    explanation: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: str = Field(min_length=1)
    insufficient_evidence: bool


INVESTIGATION_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "exception_type": {
            "type": "string",
            "enum": [t.value for t in ExceptionType],
        },
        "explanation": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "recommended_action": {"type": "string"},
        "insufficient_evidence": {"type": "boolean"},
    },
    "required": [
        "exception_type",
        "explanation",
        "confidence",
        "recommended_action",
        "insufficient_evidence",
    ],
}
