from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from finpulse.db import Base


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("source", "source_txn_id", name="uq_source_txn"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source_txn_id: Mapped[str] = mapped_column(String(64), nullable=False)
    order_ref: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    txn_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    razorpay_txn_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    bank_txn_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    ledger_txn_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    match_rule: Mapped[str] = mapped_column(String(64), nullable=False)
    ground_truth_should_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    matcher_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class ExceptionRow(Base):
    __tablename__ = "exceptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    related_txn_ids: Mapped[str] = mapped_column(Text, nullable=False)
    detected_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    exception_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ai_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reviewer: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    llm_raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    investigated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ground_truth_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    ground_truth_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ai_verdict_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    before_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")


class RunMetrics(Base):
    __tablename__ = "run_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    records_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exceptions_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wall_clock_seconds: Mapped[float | None] = mapped_column(nullable=True)
    records_per_minute: Mapped[float | None] = mapped_column(nullable=True)
    records_per_second: Mapped[float | None] = mapped_column(nullable=True)
    match_ms: Mapped[float | None] = mapped_column(nullable=True)
    investigate_ms: Mapped[float | None] = mapped_column(nullable=True)
    avg_llm_latency_ms: Mapped[float | None] = mapped_column(nullable=True)
    matcher_precision: Mapped[float | None] = mapped_column(nullable=True)
    matcher_recall: Mapped[float | None] = mapped_column(nullable=True)
    exception_accuracy_pct: Mapped[float | None] = mapped_column(nullable=True)
    manual_baseline_minutes_assumed: Mapped[float | None] = mapped_column(nullable=True)
    cash_matched_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    cash_in_transit_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    cash_exception_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
