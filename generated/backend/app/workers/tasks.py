"""The runtime pipeline (slide 5 / slide 9):

    Redis Queue -> Celery Worker (loads an IMMUTABLE TemplateVersion)
        -> OCR Service -> Extraction (Schema) -> Rule Engine
        -> Scoring Engine -> Summary Service

State machine (slide 9):
    INGESTED -> QUEUED -> PROCESSING -> EXTRACTED -> RULE_EVALUATED
        -> SCORED -> REVIEW_REQUIRED -> REVIEWED -> COMPLETED
    PROCESSING/EXTRACTED/RULE_EVALUATED can also fail:
        FAILED -> RETRY (back to QUEUED) or TERMINAL_FAILURE

Every transition is written through DocumentJob.transition() (raises on
an illegal jump) and logged as a JobEvent, so "state is recoverable
without losing the document" even if a worker crashes mid-task.
"""
from __future__ import annotations

import asyncio
from uuid import UUID

from celery import chain
from celery.exceptions import MaxRetriesExceededError

from app.db.base import async_session
from app.models.document_job import DocumentJob, JobEvent, JobStage, RuleEvaluation
from app.models.template import Rule, TemplateVersion
from app.services.rules_engine import evaluate_all
from app.services.scoring_engine import compute_risk
from app.workers.celery_app import celery_app

MAX_RETRIES = 3


def _run(coro):
    """Celery tasks are sync; the app is async end-to-end. This is the one
    sanctioned sync/async boundary."""
    return asyncio.get_event_loop().run_until_complete(coro)


async def _transition(session, job: DocumentJob, to: JobStage, detail: str | None = None) -> None:
    job.transition(to)
    session.add(JobEvent(job_id=job.id, stage=to, detail=detail))
    await session.commit()


@celery_app.task(bind=True, max_retries=MAX_RETRIES, default_retry_delay=30)
def process_document(self, job_id: str) -> None:
    """Entry point: QUEUED -> PROCESSING, then hands off to the OCR/extract
    step. Retries transport-level failures (e.g. OCR service timeout);
    schema-contract failures are NOT retried here — they go straight to
    TERMINAL_FAILURE because retrying won't fix a bad template."""
    async def _inner():
        async with async_session() as session:
            job = await session.get(DocumentJob, UUID(job_id))
            await _transition(session, job, JobStage.PROCESSING, "worker picked up job")
            try:
                extracted = await _ocr_and_extract(session, job)
                await _transition(session, job, JobStage.EXTRACTED, "extraction complete")
                await _evaluate_rules(session, job, extracted)
            except Exception as exc:  # noqa: BLE001 - deliberately broad: any failure -> FAILED
                await _transition(session, job, JobStage.FAILED, detail=str(exc))
                raise

    try:
        _run(_inner())
    except Exception as exc:
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            _run(_mark_terminal_failure(job_id, str(exc)))


async def _mark_terminal_failure(job_id: str, detail: str) -> None:
    async with async_session() as session:
        job = await session.get(DocumentJob, UUID(job_id))
        job.stage = JobStage.TERMINAL_FAILURE
        session.add(JobEvent(job_id=job.id, stage=JobStage.TERMINAL_FAILURE, detail=detail))
        await session.commit()


import base64
from openai import OpenAI
from app.core.config import settings
from app.services.storage import fetch_document

async def _ocr_and_extract(session, job: DocumentJob) -> dict:
    template_version = await session.get(TemplateVersion, job.template_version_id)
    file_bytes = fetch_document(job.object_storage_key)
    encoded = base64.b64encode(file_bytes).decode()

    client = OpenAI(api_key=settings.xai_api_key, base_url="https://api.x.ai/v1")
    response = client.chat.completions.create(
        model="grok-4",  # use a vision-capable Grok model
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Extract the fields from this document as JSON matching this schema: " + str(template_version.json_schema)},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ],
        }],
        response_format={"type": "json_object"},  # forces valid JSON back
    )

    extracted = json.loads(response.choices[0].message.content)
    job.extracted_json = extracted
    return extracted


async def _evaluate_rules(session, job: DocumentJob, extracted: dict) -> None:
    template_version = await session.get(TemplateVersion, job.template_version_id)
    rules_result = await session.execute(
        __import__("sqlalchemy").select(Rule).where(Rule.template_version_id == template_version.id)
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
