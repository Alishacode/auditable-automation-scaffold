"""Environment-driven settings. Every external dependency (DB, Redis,
object storage, AI provider) is configured here so services stay pluggable
(slide 11: "Integrated via strict service interfaces to prevent vendor
lock-in.")."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    project_name: str = "auditable-automation"

    # Persistence (slide 11: PostgreSQL + S3-compatible object storage)
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/auditable_automation"
    object_storage_endpoint: str = "http://localhost:9000"
    object_storage_bucket: str = "documents"

    # Async worker/queue (slide 11: Redis + Celery)
    redis_url: str = "redis://localhost:6379/0"

    # Pluggable AI provider used by the Template Agent (slide 6) and by the
    # OCR/extraction step of the runtime pipeline (slide 5, slide 9).
    xai_api_key: str = ""
    template_agent_model: str = "grok-4"

    class Config:
        env_file = ".env"


settings = Settings()
