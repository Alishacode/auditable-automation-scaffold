"""Workspace Admin surface: draft, edit, and PUBLISH template versions.
publish() enforces the Publish Lock (slide 7) — once called, the version
is immutable and every subsequent runtime job pins to it by id."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.models.template import TemplateVersion

router = APIRouter(prefix="/templates", tags=["templates"])


@router.post("/{template_id}/versions/{version_id}/publish")
async def publish_version(template_id: UUID, version_id: UUID, session: AsyncSession = Depends(get_session)):
    version = await session.get(TemplateVersion, version_id)
    if version is None or version.template_id != template_id:
        raise HTTPException(404, "Template version not found")
    try:
        version.publish()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await session.commit()
    return {"id": str(version.id), "status": version.status, "published_at": version.published_at}
