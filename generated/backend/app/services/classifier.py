"""Classifies a document's preview text into a known document_type using
an AI call. Deliberately takes no database session — the caller reads
known_types beforehand and persists the result afterward, in separate
steps, keeping this a plain, dependency-free function."""
from __future__ import annotations

import json

from openai import OpenAI

from app.core.config import settings

FALLBACK_DOCUMENT_TYPE = "unclassified"
CONFIDENCE_THRESHOLD = 60


def classify_sync(preview_text: str, known_types: list[str]) -> tuple[str, int]:
    """Returns (document_type, confidence_0_to_100)."""
    if not known_types:
        return FALLBACK_DOCUMENT_TYPE, 0

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
    result_json = json.loads(response.choices[0].message.content)
    doc_type = result_json.get("document_type", FALLBACK_DOCUMENT_TYPE)
    confidence = int(result_json.get("confidence", 0))

    if doc_type not in known_types or confidence < CONFIDENCE_THRESHOLD:
        return FALLBACK_DOCUMENT_TYPE, confidence
    return doc_type, confidence