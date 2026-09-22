"""Classifies an incoming document into a known Template's document_type,
using its preview text and an AI call. Falls back to the seeded
'unclassified' template when confidence is low or no known type matches.
"""
from __future__ import annotations

import asyncio
import json

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.template import Template

FALLBACK_DOCUMENT_TYPE = "unclassified"
CONFIDENCE_THRESHOLD = 60


async def classify_document(session: AsyncSession, preview_text: str) -> tuple[str, int]:
    """Returns (document_type, confidence_0_to_100)."""
    result = await session.execute(select(Template.document_type).distinct())
    known_types = [row[0] for row in result.all() if row[0] != FALLBACK_DOCUMENT_TYPE]

    if not known_types:
        return FALLBACK_DOCUMENT_TYPE, 0

    def _call_groq():
        client = OpenAI(api_key=settings.xai_api_key, base_url="https://api.groq.com/openai/v1")
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{
                "role": "user",
                "content": (
                    f"Known document types: {known_types}\n\n"
                    f"Document preview:\n{preview_text}\n\n"
                    'Which known document type best matches this document? '
                    'Respond as JSON: {"document_type": "...", "confidence": 0-100}. '
                    "If none match well, use confidence below 60."
                ),
            }],
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content

    raw_json = await asyncio.to_thread(_call_groq)
    result_json = json.loads(raw_json)

    doc_type = result_json.get("document_type", FALLBACK_DOCUMENT_TYPE)
    confidence = int(result_json.get("confidence", 0))

    if doc_type not in known_types or confidence < CONFIDENCE_THRESHOLD:
        return FALLBACK_DOCUMENT_TYPE, confidence

    return doc_type, confidence