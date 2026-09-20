"""Schema Validator (slide 6): "Runs before any testing, rejecting
malformed structures and demanding AI regeneration if necessary." This
gate sits between the Template Agent's raw output and anything a human
or the runtime pipeline ever sees."""
from __future__ import annotations

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


class SchemaValidationError(Exception):
    pass


def validate_json_schema(candidate: dict) -> None:
    """Raises SchemaValidationError if `candidate` is not itself a
    syntactically/semantically valid JSON Schema. Does not validate a
    document AGAINST the schema — that happens at runtime extraction
    time; this only validates the schema itself, matching slide 14's
    "Metric 2: Schema Validity ... AI-generated schemas passing strict
    syntax/semantic validation on very first generation."""
    if not isinstance(candidate, dict):
        raise SchemaValidationError("Schema must be a JSON object.")
    if candidate.get("type") not in (None, "object"):
        raise SchemaValidationError('Top-level schema type must be "object".')
    if "properties" not in candidate:
        raise SchemaValidationError('Schema is missing a "properties" block.')

    try:
        Draft202012Validator.check_schema(candidate)
    except SchemaError as exc:
        raise SchemaValidationError(str(exc)) from exc
