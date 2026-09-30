"""Document ingestion. /upload accepts a real browser file upload and
does everything test_ingest.py did manually: stores it in MinIO, creates
a DocumentJob, and enqueues the pipeline."""
import uuid

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.models.document_job import DocumentJob, JobEvent, JobStage
from app.services.storage import upload_document
from app.workers.tasks import process_document

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload")
async def upload_and_ingest(file: UploadFile, session: AsyncSession = Depends(get_session)):
    file_bytes = await file.read()
    key = f"uploads/{uuid.uuid4()}_{file.filename}"
    upload_document(file_bytes, key)

    job = DocumentJob(template_version_id=None, object_storage_key=key)
    session.add(job)
    await session.flush()
    session.add(JobEvent(job_id=job.id, stage=JobStage.INGESTED, detail=f"uploaded: {file.filename}"))
    job.stage = JobStage.QUEUED
    session.add(JobEvent(job_id=job.id, stage=JobStage.QUEUED, detail="enqueued for processing"))
    await session.commit()

    process_document.delay(str(job.id))
    return {"job_id": str(job.id), "stage": job.stage}


@router.post("/ingest")
async def ingest_document(object_storage_key: str, session: AsyncSession = Depends(get_session)):
    """Kept for the manual test_ingest.py script."""
    job = DocumentJob(template_version_id=None, object_storage_key=object_storage_key)
    session.add(job)
    await session.flush()
    session.add(JobEvent(job_id=job.id, stage=JobStage.INGESTED, detail="document uploaded"))
    job.stage = JobStage.QUEUED
    session.add(JobEvent(job_id=job.id, stage=JobStage.QUEUED, detail="enqueued for processing"))
    await session.commit()

    process_document.delay(str(job.id))
    return {"job_id": str(job.id), "stage": job.stage}