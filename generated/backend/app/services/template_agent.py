"""Design-time AI agent, using Grok (xAI) instead of Claude."""
from __future__ import annotations

import json

from openai import OpenAI

from app.core.config import settings
from app.services.schema_validator import SchemaValidationError, validate_json_schema

MAX_REGENERATION_ATTEMPTS = 3


class TemplateAgent:
    def __init__(self):
        # Same OpenAI library, just pointed at xAI's servers instead of OpenAI's.
        self.client = OpenAI(api_key=settings.xai_api_key, base_url="https://api.x.ai/v1")

    def draft_schema(self, natural_language_intent: str) -> dict:
        system_prompt = (
            "Draft a JSON Schema that captures the extraction contract described "
            "by the user's intent. Respond with JSON Schema only, no markdown fences."
        )
        last_error = None

        for attempt in range(1, MAX_REGENERATION_ATTEMPTS + 1):
            user_msg = (
                f"Intent: {natural_language_intent}\nGenerate the JSON Schema now."
                if last_error is None else
                f"Your previous output failed validation: {last_error}. Regenerate it correctly."
            )
            response = self.client.chat.completions.create(
                model=settings.template_agent_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
            )
            raw_text = response.choices[0].message.content
            try:
                candidate = json.loads(raw_text)
                validate_json_schema(candidate)
                return candidate
            except (json.JSONDecodeError, SchemaValidationError) as exc:
                last_error = exc
                continue

        raise SchemaValidationError(f"Failed after {MAX_REGENERATION_ATTEMPTS} attempts. Last error: {last_error}")