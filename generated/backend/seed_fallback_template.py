"""Run once: python seed_fallback_template.py
Creates a generic fallback Template + published TemplateVersion for
documents that don't match any specific configured template."""
import asyncio

from app.db.base import async_session
from app.models.template import Template, TemplateVersion, ScoringConfig

FALLBACK_SCHEMA = {
    "type": "object",
    "properties": {
        "raw_text": {"type": "string", "description": "Best-effort extracted text"},
    },
    "required": ["raw_text"],
}

FALLBACK_PROMPT = (
    "This document did not match any configured template. Extract any "
    "readable text as-is into the 'raw_text' field."
)


async def seed():
    async with async_session() as session:
        template = Template(
            name="Generic Fallback",
            document_type="unclassified",
            natural_language_intent="Fallback for documents that don't match a known type.",
        )
        session.add(template)
        await session.flush()  # get template.id without committing yet

        version = TemplateVersion(
            template_id=template.id,
            version_number="1.0.0",
            json_schema=FALLBACK_SCHEMA,
            system_prompt=FALLBACK_PROMPT,
        )
        session.add(version)
        await session.flush()

        version.publish()  # locks it — matches your Publish Lock rule

        session.add(ScoringConfig(
            template_version_id=version.id,
            low_max=100,   # fallback docs never auto-score risk
            medium_max=1000,
        ))

        await session.commit()
        print(f"Seeded fallback template: template_id={template.id}, version_id={version.id}")


if __name__ == "__main__":
    asyncio.run(seed())