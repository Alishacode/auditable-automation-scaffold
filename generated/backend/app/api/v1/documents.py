"""Document ingestion: creates a DocumentJob and enqueues the runtime
pipeline. The template version is no longer chosen by the caller — the
CLASSIFYING stage picks it automatically based on the document's content
(see app/services/classifier.py)."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.models.document_job import DocumentJob, JobEvent, JobStage
from app.workers.tasks import process_document

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/ingest")
async def ingest_document(object_storage_key: str, session: AsyncSession = Depends(get_session)):
    job = DocumentJob(template_version_id=None, object_storage_key=object_storage_key)
    session.add(job)
    await session.flush()
    session.add(JobEvent(job_id=job.id, stage=JobStage.INGESTED, detail="document uploaded"))
    job.stage = JobStage.QUEUED
    session.add(JobEvent(job_id=job.id, stage=JobStage.QUEUED, detail="enqueued for processing"))
    await session.commit()

    process_document.delay(str(job.id))
    return {"job_id": str(job.id), "stage": job.stage}