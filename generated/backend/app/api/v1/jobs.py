"""Reviewer surface (slide 4/13): the prioritized queue plus the full
document-preview + structured-JSON + risk-scorecard payload."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.models.document_job import DocumentJob, JobStage

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/review-queue")
async def review_queue(session: AsyncSession = Depends(get_session)):
    """Jobs sitting at REVIEW_REQUIRED, highest risk first (slide 13
    "Reviewer Queue")."""
    result = await session.execute(
        select(DocumentJob)
        .where(DocumentJob.stage == JobStage.REVIEW_REQUIRED)
        .order_by(DocumentJob.risk_score.desc())
    )
    jobs = result.scalars().all()
    return [
        {"id": str(j.id), "risk_score": j.risk_score, "risk_level": j.risk_level, "stage": j.stage}
        for j in jobs
    ]


@router.get("/{job_id}")
async def get_job(job_id: UUID, session: AsyncSession = Depends(get_session)):
    job = await session.get(DocumentJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return {
        "id": str(job.id),
        "stage": job.stage,
        "extracted_json": job.extracted_json,
        "risk_score": job.risk_score,
        "risk_level": job.risk_level,
        "ai_summary": job.ai_summary,
    }
