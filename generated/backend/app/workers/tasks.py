"""The runtime pipeline:

    Redis Queue -> Celery Worker
        -> CLASSIFYING (pick a template automatically)
        -> Extraction (Grok vision, schema-constrained) -> Rule Engine
        -> Scoring Engine -> Summary Service

State machine:
    INGESTED -> QUEUED -> CLASSIFYING -> PROCESSING -> EXTRACTED
        -> RULE_EVALUATED -> SCORED -> REVIEW_REQUIRED -> REVIEWED -> COMPLETED
    CLASSIFYING/PROCESSING/EXTRACTED/RULE_EVALUATED can also fail:
        FAILED -> RETRY (back to QUEUED) or TERMINAL_FAILURE
"""
from __future__ import annotations

import asyncio
from app.db.base import engine
import json
from uuid import UUID
from xmlrpc import client

from celery.exceptions import MaxRetriesExceededError
from openai import OpenAI
from sqlalchemy import select

from app.core.config import settings
from app.db.base import async_session
from app.models.document_job import DocumentJob, JobEvent, JobStage, RuleEvaluation
from app.models.template import Rule, Template, TemplateVersion
from app.services.classifier import classify_document
from app.services.rules_engine import evaluate_all
from app.services.scoring_engine import compute_risk
from app.services.storage import fetch_document
from app.services.text_extraction import extract_preview_text
from app.workers.celery_app import celery_app

MAX_RETRIES = 3


def _run(coro):
    """Celery tasks are sync; the app is async end-to-end. asyncio.run()
    creates a fresh event loop every call. We also explicitly dispose the
    database engine's connections after every run (success OR failure) so
    a broken/stale connection can never leak into the next retry attempt
    — this is what was causing 'another operation is in progress'."""
    async def _wrapped():
        try:
            return await coro
        finally:
            await engine.dispose()
    return asyncio.run(_wrapped())


async def _transition(session, job: DocumentJob, to: JobStage, detail: str | None = None) -> None:
    job.transition(to)
    session.add(JobEvent(job_id=job.id, stage=to, detail=detail))
    await session.commit()


@celery_app.task(bind=True, max_retries=MAX_RETRIES, default_retry_delay=30)
def process_document(self, job_id: str) -> None:
    """Entry point: QUEUED -> CLASSIFYING -> PROCESSING, then extraction/
    rules/scoring. Retries transport-level failures; schema-contract
    failures go straight to TERMINAL_FAILURE since retrying won't fix a
    bad template."""
    try:
        _run(_inner(job_id))
    except Exception as exc:
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            _run(_mark_terminal_failure(job_id, str(exc)))


async def _inner(job_id: str) -> None:
    async with async_session() as session:
        job = await session.get(DocumentJob, UUID(job_id))

        # ---- CLASSIFYING ----
        await _transition(session, job, JobStage.CLASSIFYING, "classifying document type")
        try:
            file_bytes = fetch_document(job.object_storage_key)
            preview_text = extract_preview_text(file_bytes)
            doc_type, confidence = await classify_document(session, preview_text)
            job.classification_confidence = confidence

            result = await session.execute(
                select(TemplateVersion)
                .join(Template, Template.id == TemplateVersion.template_id)
                .where(Template.document_type == doc_type)
                .where(TemplateVersion.status == "published")
                .order_by(TemplateVersion.published_at.desc())
                .limit(1)
            )
            version = result.scalar_one_or_none()
            if version is None:
                raise ValueError(f"No published template found for document_type={doc_type}")

            job.template_version_id = version.id
            await session.commit()
        except Exception as exc:
            await _transition(session, job, JobStage.FAILED, detail=f"classification failed: {exc}")
            raise

        # ---- PROCESSING (extraction + rules + scoring) ----
        await _transition(session, job, JobStage.PROCESSING, f"classified as {doc_type} ({confidence}% confidence)")
        try:
            extracted = await _ocr_and_extract(session, job)
            await _transition(session, job, JobStage.EXTRACTED, "extraction complete")
            await _evaluate_rules(session, job, extracted)
        except Exception as exc:
            await _transition(session, job, JobStage.FAILED, detail=str(exc))
            raise


async def _mark_terminal_failure(job_id: str, detail: str) -> None:
    async with async_session() as session:
        job = await session.get(DocumentJob, UUID(job_id))
        job.stage = JobStage.TERMINAL_FAILURE
        session.add(JobEvent(job_id=job.id, stage=JobStage.TERMINAL_FAILURE, detail=detail))
        await session.commit()


async def _ocr_and_extract(session, job: DocumentJob) -> dict:
    """Text-based structured extraction via Groq."""
    template_version = await session.get(TemplateVersion, job.template_version_id)
    file_bytes = fetch_document(job.object_storage_key)
    full_text = extract_preview_text(file_bytes, max_chars=8000)
    schema_str = json.dumps(template_version.json_schema)

    # Run the synchronous Groq call in a background thread so it doesn't
    # interfere with the async database session's context.
    def _call_groq():
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

    raw_json = await asyncio.to_thread(_call_groq)
    extracted = json.loads(raw_json)

    job.extracted_json = extracted
    await session.commit()
    return extracted


async def _evaluate_rules(session, job: DocumentJob, extracted: dict) -> None:
    template_version = await session.get(TemplateVersion, job.template_version_id)
    rules_result = await session.execute(
        select(Rule).where(Rule.template_version_id == template_version.id)
    )
    rules: list[Rule] = list(rules_result.scalars())

    results = evaluate_all(rules, extracted)
    for r in results:
        session.add(RuleEvaluation(
            job_id=job.id, rule_id=r["rule_id"], passed=r["passed"],
            score_delta_applied=r["score_delta_applied"],
        ))
    await _transition(session, job, JobStage.RULE_EVALUATED, f"{len(results)} rules evaluated")

    total, level, reasons = compute_risk(results, template_version.scoring_config)
    job.risk_score = total
    job.risk_level = level
    await _transition(session, job, JobStage.SCORED, f"score={total} level={level}")

    next_stage = JobStage.REVIEW_REQUIRED if level in ("medium", "high") else JobStage.COMPLETED
    await _transition(session, job, next_stage, "; ".join(reasons) or None)
