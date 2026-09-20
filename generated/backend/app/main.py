"""FastAPI entrypoint for auditable-automation."""
from fastapi import FastAPI

from app.api.v1 import documents, jobs, templates
from app.core.config import settings

app = FastAPI(title=settings.project_name)

app.include_router(templates.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
