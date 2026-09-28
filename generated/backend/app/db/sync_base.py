"""Synchronous SQLAlchemy engine, used only by the Celery worker.

A Celery worker (especially with --pool=solo) handles one task at a
time in a single thread — there's no concurrency to gain from async DB
access here. Mixing greenlet-based async SQLAlchemy with a blocking AI
call inside one task was the root cause of a recurring MissingGreenlet
bug. The worker now uses a plain sync session instead; the FastAPI app
keeps using the async engine in app/db/base.py, where async genuinely
helps.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

_sync_url = settings.database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")

sync_engine = create_engine(_sync_url, echo=False, future=True)
SyncSession = sessionmaker(bind=sync_engine, expire_on_commit=False)