"""Document ingestion: creates a DocumentJob pinned to an immutable
TemplateVersion and enqueues the runtime pipeline (slide 9)."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.models.document_job import DocumentJob, JobEvent, JobStage
from app.models.template import TemplateVersion, TemplateVersionStatus
from app.workers.tasks import process_document

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/ingest")
async def ingest_document(
    template_version_id: UUID, object_storage_key: str, session: AsyncSession = Depends(get_session)
):
    version = await session.get(TemplateVersion, template_version_id)
    if version is None:
        raise HTTPException(404, "Template version not found")
    if version.status != TemplateVersionStatus.PUBLISHED:
        raise HTTPException(409, "Documents may only be processed against a PUBLISHED template version")

    job = DocumentJob(template_version_id=version.id, object_storage_key=object_storage_key)
    session.add(job)
    await session.flush()
    session.add(JobEvent(job_id=job.id, stage=JobStage.INGESTED, detail="document uploaded"))
    job.stage = JobStage.QUEUED
    session.add(JobEvent(job_id=job.id, stage=JobStage.QUEUED, detail="enqueued for processing"))
    await session.commit()

    process_document.delay(str(job.id))
    return {"job_id": str(job.id), "stage": job.stage}
