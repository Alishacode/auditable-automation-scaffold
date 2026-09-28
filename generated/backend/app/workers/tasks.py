"""The runtime pipeline — now fully synchronous. Celery already runs one
task at a time (--pool=solo); async DB access bought nothing here and
caused a recurring MissingGreenlet bug, so the worker uses a plain sync
SQLAlchemy session (app/db/sync_base.py) instead.

State machine:
    INGESTED -> QUEUED -> CLASSIFYING -> PROCESSING -> EXTRACTED
        -> RULE_EVALUATED -> SCORED -> REVIEW_REQUIRED -> REVIEWED -> COMPLETED
    On failure: FAILED -> reset to QUEUED for retry, or TERMINAL_FAILURE
    once retries are exhausted.
"""
from __future__ import annotations

import json
from uuid import UUID

from celery.exceptions import MaxRetriesExceededError
from openai import OpenAI
from sqlalchemy import select

from app.core.config import settings
from app.db.sync_base import SyncSession
from app.models.document_job import DocumentJob, JobEvent, JobStage, RuleEvaluation
from app.models.template import Rule, Template, TemplateVersion
from app.services.classifier import FALLBACK_DOCUMENT_TYPE, classify_sync
from app.services.rules_engine import evaluate_all
from app.services.scoring_engine import compute_risk
from app.services.storage import fetch_document
from app.services.text_extraction import extract_preview_text
from app.workers.celery_app import celery_app

MAX_RETRIES = 3


def _transition(session, job: DocumentJob, to: JobStage, detail: str | None = None) -> None:
    job.transition(to)
    session.add(JobEvent(job_id=job.id, stage=to, detail=detail))
    session.commit()


@celery_app.task(bind=True, max_retries=MAX_RETRIES, default_retry_delay=30)
def process_document(self, job_id: str) -> None:
    try:
        _inner(job_id)
    except Exception as exc:
        # Reset to QUEUED so a retry can legally re-enter CLASSIFYING —
        # otherwise a retry hits "FAILED -> CLASSIFYING" (illegal).
        with SyncSession() as session:
            job = session.get(DocumentJob, UUID(job_id))
            if job and job.stage not in (JobStage.TERMINAL_FAILURE, JobStage.COMPLETED):
                job.stage = JobStage.QUEUED
                session.add(JobEvent(job_id=job.id, stage=JobStage.QUEUED, detail=f"retry after: {exc}"))
                session.commit()
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            with SyncSession() as session:
                job = session.get(DocumentJob, UUID(job_id))
                job.stage = JobStage.TERMINAL_FAILURE
                session.add(JobEvent(job_id=job.id, stage=JobStage.TERMINAL_FAILURE, detail=str(exc)))
                session.commit()


def _inner(job_id: str) -> None:
    with SyncSession() as session:
        job = session.get(DocumentJob, UUID(job_id))
        _transition(session, job, JobStage.CLASSIFYING, "classifying document type")

        file_bytes = fetch_document(job.object_storage_key)
        preview_text = extract_preview_text(file_bytes)
        known_types = [
            row[0] for row in session.execute(select(Template.document_type).distinct()).all()
            if row[0] != FALLBACK_DOCUMENT_TYPE
        ]

        doc_type, confidence = classify_sync(preview_text, known_types)
        job.classification_confidence = confidence

        version = session.execute(
            select(TemplateVersion)
            .join(Template, Template.id == TemplateVersion.template_id)
            .where(Template.document_type == doc_type)
            .where(TemplateVersion.status == "published")
            .order_by(TemplateVersion.published_at.desc())
            .limit(1)
        ).scalars().first()
        if version is None:
            raise ValueError(f"No published template found for document_type={doc_type}")

        job.template_version_id = version.id
        _transition(session, job, JobStage.PROCESSING, f"classified as {doc_type} ({confidence}% confidence)")
        full_text = extract_preview_text(file_bytes, max_chars=8000)
        is_generic = doc_type == FALLBACK_DOCUMENT_TYPE
        if is_generic:
            raw_json = _extract_generic_sync(full_text)
        else:
            raw_json = _extract_sync(json.dumps(version.json_schema), full_text)
        extracted = json.loads(raw_json)
        job.extracted_json = extracted
        _transition(session, job, JobStage.EXTRACTED, "extraction complete")

        rules = session.execute(
            select(Rule).where(Rule.template_version_id == version.id)
        ).scalars().all()

        results = evaluate_all(list(rules), extracted)
        for r in results:
            session.add(RuleEvaluation(
                job_id=job.id, rule_id=r["rule_id"], passed=r["passed"],
                score_delta_applied=r["score_delta_applied"],
            ))
        _transition(session, job, JobStage.RULE_EVALUATED, f"{len(results)} rules evaluated")

        total, level, reasons = compute_risk(results, version.scoring_config)
        if is_generic and len(extracted.get("fields", {})) < 3:
            total, level = max(total, 40), "medium"
            reasons.append("Few fields extracted from an unrecognised document")
        job.risk_score = total
        job.risk_level = level
        _transition(session, job, JobStage.SCORED, f"score={total} level={level}")

        next_stage = JobStage.REVIEW_REQUIRED if level in ("medium", "high") else JobStage.COMPLETED
        _transition(session, job, next_stage, "; ".join(reasons) or None)


def _extract_sync(schema_str: str, full_text: str) -> str:
    client = OpenAI(api_key=settings.xai_api_key, base_url="https://api.groq.com/openai/v1")
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{
            "role": "user",
            "content": f"Extract the fields from this document as JSON matching this schema: {schema_str}\n\nDocument text:\n{full_text}",
        }],
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content

def _extract_generic_sync(full_text: str) -> str:
    client = OpenAI(api_key=settings.xai_api_key, base_url="https://api.groq.com/openai/v1")
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{
            "role": "user",
            "content": (
                "Read this document and extract every meaningful piece of data in it. "
                'Respond as JSON: {"document_type_guess": "...", "summary": "one sentence", '
                '"fields": {"field_name": "value", ...}}. Use clear snake_case field names.\n\n'
                f"Document text:\n{full_text}"
            ),
        }],
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content
