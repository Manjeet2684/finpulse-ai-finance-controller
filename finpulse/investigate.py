from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from time import perf_counter

from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from finpulse.config import get_settings
from finpulse.enums import (
    LOW_CONFIDENCE_RETRY,
    ActorType,
    ExceptionStatus,
)
from finpulse.ingest import write_audit
from finpulse.models import ExceptionRow, Match, Transaction
from finpulse.policy import apply_policy
from finpulse.prompt import (
    PROMPT_VERSION,
    RETRY_INSTRUCTION,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
)
from finpulse.schemas import INVESTIGATION_JSON_SCHEMA, InvestigationResult


@dataclass
class InvestigateJob:
    exception_id: int
    order_ref: str
    detected_reason: str
    records: list[dict]


@dataclass
class InvestigateOutcome:
    exception_id: int
    result: InvestigationResult | None
    raw_response: str
    latency_ms: float
    retried: bool
    error: str | None = None


def _record_payload(txn: Transaction, matched_ids: set[int]) -> dict:
    return {
        "source": txn.source,
        "source_txn_id": txn.source_txn_id,
        "order_ref": txn.order_ref,
        "amount": f"{Decimal(txn.amount):.2f}",
        "currency": txn.currency,
        "txn_time": txn.txn_time.isoformat(),
        "status": txn.status,
        "description": txn.description,
        "matched": txn.id in matched_ids,
    }


def build_jobs(db: Session, run_id: str, force: bool = False) -> list[InvestigateJob]:
    rows = db.query(ExceptionRow).filter(ExceptionRow.run_id == run_id).all()
    matches = db.query(Match).filter(Match.run_id == run_id).all()
    matched_ids = {m.razorpay_txn_id for m in matches} | {m.bank_txn_id for m in matches} | {m.ledger_txn_id for m in matches}
    jobs: list[InvestigateJob] = []
    for row in rows:
        if row.investigated_at is not None and not force:
            continue
        related_ids = json.loads(row.related_txn_ids)
        related = db.query(Transaction).filter(Transaction.id.in_(related_ids)).all()
        if not related:
            continue
        order_ref = related[0].order_ref
        all_on_order = (
            db.query(Transaction)
            .filter(Transaction.order_ref == order_ref)
            .order_by(Transaction.source, Transaction.source_txn_id)
            .all()
        )
        jobs.append(
            InvestigateJob(
                exception_id=row.id,
                order_ref=order_ref,
                detected_reason=row.detected_reason,
                records=[_record_payload(t, matched_ids) for t in all_on_order],
            )
        )
    return jobs


def _retry_wait_seconds(exc: Exception) -> float | None:
    text = str(exc)
    if "GenerateRequestsPerDayPerProjectPerModel" in text:
        return None
    match = re.search(r"Please retry in ([\d.]+)s", text)
    if match:
        return min(float(match.group(1)) + 2.0, 90.0)
    if "429" in text or "RESOURCE_EXHAUSTED" in text:
        return 45.0
    return None


def _client(settings=None) -> AsyncOpenAI:
    settings = settings or get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is missing. Put it in .env before investigation.")
    return AsyncOpenAI(api_key=settings.gemini_api_key, base_url=settings.gemini_base_url)


async def investigate(
    job: InvestigateJob,
    retry: bool = False,
    client: AsyncOpenAI | None = None,
) -> tuple[InvestigationResult, str]:
    """Single LLM call. Provider is swappable by replacing this function."""
    settings = get_settings()
    if client is None:
        client = _client(settings)

    user = USER_PROMPT_TEMPLATE.format(
        prompt_version=PROMPT_VERSION,
        order_ref=job.order_ref,
        detected_reason=job.detected_reason,
        records_json=json.dumps(job.records, indent=2),
    )
    if retry:
        user = user + "\n\n" + RETRY_INSTRUCTION

    last_error: Exception | None = None
    for attempt in range(6):
        try:
            response = await client.chat.completions.create(
                model=settings.gemini_model,
                temperature=0,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "investigation_result",
                        "strict": True,
                        "schema": INVESTIGATION_JSON_SCHEMA,
                    },
                },
            )
            raw = response.choices[0].message.content or ""
            parsed = InvestigationResult.model_validate_json(raw)
            return parsed, raw
        except Exception as exc:  # noqa: BLE001 — quota backoff only; then raise
            last_error = exc
            wait = _retry_wait_seconds(exc)
            if attempt < 5 and wait is not None:
                await asyncio.sleep(wait)
                continue
            raise
    raise last_error or RuntimeError("investigate() failed")


async def _investigate_with_retry(job: InvestigateJob, client: AsyncOpenAI) -> InvestigateOutcome:
    t0 = perf_counter()
    retried = False
    try:
        result, raw = await investigate(job, retry=False, client=client)
        if result.confidence < LOW_CONFIDENCE_RETRY and not result.insufficient_evidence:
            retried = True
            result, raw = await investigate(job, retry=True, client=client)
        return InvestigateOutcome(
            exception_id=job.exception_id,
            result=result,
            raw_response=raw,
            latency_ms=(perf_counter() - t0) * 1000,
            retried=retried,
        )
    except Exception as exc:  # noqa: BLE001 — failed calls become UNRESOLVED
        return InvestigateOutcome(
            exception_id=job.exception_id,
            result=None,
            raw_response="",
            latency_ms=(perf_counter() - t0) * 1000,
            retried=retried,
            error=str(exc),
        )


async def investigate_jobs(jobs: list[InvestigateJob], concurrency: int | None = None) -> list[InvestigateOutcome]:
    settings = get_settings()
    limit = concurrency or settings.finpulse_llm_concurrency
    sem = asyncio.Semaphore(limit)
    client = _client(settings)
    async with client:

        async def bounded(job: InvestigateJob) -> InvestigateOutcome:
            async with sem:
                return await _investigate_with_retry(job, client)

        return await asyncio.gather(*[bounded(job) for job in jobs])


def persist_outcomes(db: Session, outcomes: list[InvestigateOutcome]) -> dict:
    latencies: list[float] = []
    for outcome in outcomes:
        row = db.query(ExceptionRow).filter(ExceptionRow.id == outcome.exception_id).one()
        before = {"status": row.status, "exception_type": row.exception_type}
        latencies.append(outcome.latency_ms)
        row.llm_raw_response = outcome.raw_response or outcome.error
        if outcome.result is None:
            row.exception_type = None
            row.ai_explanation = f"LLM call failed: {outcome.error}"
            row.confidence = None
            row.recommended_action = None
            row.status = ExceptionStatus.UNRESOLVED
            # Quota/network failures are not investigations — leave cache unset so resume can retry.
            row.investigated_at = None
        else:
            row.investigated_at = datetime.utcnow()
            row.exception_type = outcome.result.exception_type.value
            row.ai_explanation = outcome.result.explanation
            row.confidence = outcome.result.confidence
            row.recommended_action = outcome.result.recommended_action
            row.status = apply_policy(
                confidence=outcome.result.confidence,
                insufficient_evidence=outcome.result.insufficient_evidence,
                exception_type=outcome.result.exception_type,
            ).value
        write_audit(
            db,
            ActorType.AI,
            "INVESTIGATE",
            str(row.id),
            reason=PROMPT_VERSION + ("; retry" if outcome.retried else ""),
            before_state=before,
            after_state={
                "status": row.status,
                "exception_type": row.exception_type,
                "confidence": row.confidence,
                "error": outcome.error,
            },
        )
    avg = (sum(latencies) / len(latencies)) if latencies else None
    return {
        "investigated": len(outcomes),
        "failed": sum(1 for o in outcomes if o.result is None),
        "retried": sum(1 for o in outcomes if o.retried),
        "avg_llm_latency_ms": avg,
        "latencies_ms": latencies,
    }


def run_investigation(db: Session, run_id: str, force: bool = False) -> dict:
    jobs = build_jobs(db, run_id, force=force)
    if not jobs:
        return {"investigated": 0, "failed": 0, "retried": 0, "avg_llm_latency_ms": None, "latencies_ms": []}
    outcomes = asyncio.run(investigate_jobs(jobs))
    return persist_outcomes(db, outcomes)
