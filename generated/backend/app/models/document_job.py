"""DocumentJob: the runtime state machine, and JobEvent: the append-only
audit trail behind every reviewer-facing risk score."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class JobStage(str, enum.Enum):
    """Exact pipeline stages from slide 9's state-machine diagram."""
    INGESTED = "INGESTED"
    QUEUED = "QUEUED"
    CLASSIFYING = "CLASSIFYING"   # NEW
    PROCESSING = "PROCESSING"
    EXTRACTED = "EXTRACTED"
    RULE_EVALUATED = "RULE_EVALUATED"
    SCORED = "SCORED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REVIEWED = "REVIEWED"
    COMPLETED = "COMPLETED"
    # Failure branch off PROCESSING (slide 9): FAILED -> RETRY / TERMINAL_FAILURE
    FAILED = "FAILED"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"


# Stages a job is allowed to move to from a given stage. The Celery task
# chain (app/workers/tasks.py) checks this before every transition so a
# buggy task can never silently skip or corrupt the audit trail.
ALLOWED_TRANSITIONS: dict[JobStage, set[JobStage]] = {
    JobStage.INGESTED: {JobStage.QUEUED},
    JobStage.QUEUED: {JobStage.PROCESSING},
    JobStage.PROCESSING: {JobStage.EXTRACTED, JobStage.FAILED},
    JobStage.EXTRACTED: {JobStage.RULE_EVALUATED, JobStage.FAILED},
    JobStage.RULE_EVALUATED: {JobStage.SCORED, JobStage.FAILED},
    JobStage.SCORED: {JobStage.REVIEW_REQUIRED, JobStage.COMPLETED},
    JobStage.REVIEW_REQUIRED: {JobStage.REVIEWED},
    JobStage.REVIEWED: {JobStage.COMPLETED},
    JobStage.FAILED: {JobStage.QUEUED, JobStage.TERMINAL_FAILURE},  # retry or give up
    JobStage.COMPLETED: set(),
    JobStage.TERMINAL_FAILURE: set(),
}


class DocumentJob(Base):
    __tablename__ = "document_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    template_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("template_versions.id"))
    object_storage_key: Mapped[str] = mapped_column(String(512), nullable=False)  # raw doc blob
    stage: Mapped[JobStage] = mapped_column(Enum(JobStage), default=JobStage.INGESTED)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    extracted_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)  # low/medium/high
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    events: Mapped[list["JobEvent"]] = relationship(back_populates="job", order_by="JobEvent.created_at")
    rule_evaluations: Mapped[list["RuleEvaluation"]] = relationship(back_populates="job")

    def transition(self, to: JobStage) -> None:
        allowed = ALLOWED_TRANSITIONS[self.stage]
        if to not in allowed:
            raise ValueError(f"Illegal transition {self.stage} -> {to}. Allowed: {allowed}")
        self.stage = to


class JobEvent(Base):
    """Append-only log entry for every stage transition. This is what lets
    a Platform Developer say "state is recoverable without losing the
    document" (slide 9) after a crash mid-pipeline."""

    __tablename__ = "job_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_jobs.id"))
    stage: Mapped[JobStage] = mapped_column(Enum(JobStage), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    job: Mapped["DocumentJob"] = relationship(back_populates="events")


class RuleEvaluation(Base):
    """One row per rule fired for one job: exactly the trace shown on
    slide 10 (Rule_ID_412 -> +50 points -> Risk Level: HIGH)."""

    __tablename__ = "rule_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_jobs.id"))
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rules.id"))
    passed: Mapped[bool] = mapped_column(nullable=False)
    score_delta_applied: Mapped[int] = mapped_column(Integer, nullable=False)

    job: Mapped["DocumentJob"] = relationship(back_populates="rule_evaluations")
