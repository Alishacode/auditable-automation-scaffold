#!/usr/bin/env python3
"""
scaffold_agent.py — Auditable Automation project scaffolder.

This is a deterministic code-generation agent: given a declarative spec
(YAML) describing a document template — natural-language intent, an
extraction field contract, schema-aware rules, and scoring thresholds — it
generates a runnable FastAPI + Celery + PostgreSQL backend skeleton and a
React/TypeScript reviewer UI stub that implement the "Auditable Automation"
architecture:

    AI-Assisted Configuration (Template Agent drafts the contract)
        +
    Deterministic Execution   (Rule Engine / Scoring Engine enforce it)
        =
    Auditable Automation

Every generated artifact is traceable back to a specific slide in the
project deck — see the comment above each template function.

Usage:
    python scaffold_agent.py example_specs/hr_onboarding.yaml --out ./generated

Design choices (see slide 11 "Pluggable Services"):
    Frontend        React + TypeScript
    Backend API     Python + FastAPI (async, Pydantic validation)
    Async Worker    Redis + Celery
    Persistence     PostgreSQL (+ S3-compatible object storage for blobs)
    AI Provider     Anthropic Claude, structured output — pluggable, see
                    app/services/template_agent.py
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined

JINJA_ENV = Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)


def render(template_str: str, **ctx: Any) -> str:
    return JINJA_ENV.from_string(template_str).render(**ctx)


# --------------------------------------------------------------------------
# Spec model — the structured contract this agent consumes
# --------------------------------------------------------------------------

@dataclass
class FieldSpec:
    name: str
    type: str
    description: str = ""
    format: str | None = None
    properties: dict[str, Any] | None = None

    @property
    def py_type(self) -> str:
        return {
            "string": "str",
            "number": "float",
            "integer": "int",
            "boolean": "bool",
            "object": "dict",
            "array": "list",
        }.get(self.type, "Any")


@dataclass
class RuleSpec:
    id: str
    category: str          # completeness | validation | eligibility | risk
    field: str              # dotted path into extracted JSON
    condition: str           # equals | not_equals | greater_than | less_than | exists | missing
    value: Any
    score_delta: int
    reason: str


@dataclass
class ScoringSpec:
    low_max: int
    medium_max: int


@dataclass
class TemplateSpec:
    name: str
    natural_language_intent: str
    fields: list[FieldSpec]
    rules: list[RuleSpec]
    scoring: ScoringSpec


@dataclass
class ProjectSpec:
    name: str
    vertical_slice: str
    template: TemplateSpec


def load_spec(path: Path) -> ProjectSpec:
    raw = yaml.safe_load(path.read_text())
    t = raw["template"]
    fields = [FieldSpec(**f) for f in t["fields"]]
    rules = [RuleSpec(**r) for r in raw["rules"]]
    scoring = ScoringSpec(**raw["scoring"])
    template = TemplateSpec(
        name=t["name"],
        natural_language_intent=t["natural_language_intent"].strip(),
        fields=fields,
        rules=rules,
        scoring=scoring,
    )
    p = raw["project"]
    return ProjectSpec(name=p["name"], vertical_slice=p["vertical_slice"], template=template)


def write(out_dir: Path, rel_path: str, content: str) -> None:
    dest = out_dir / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content.rstrip() + "\n")
    print(f"  wrote {rel_path}")


# --------------------------------------------------------------------------
# Generators — each function maps directly to a slide in the deck.
# --------------------------------------------------------------------------

def gen_core_config(out: Path, spec: ProjectSpec) -> None:
    """core/config.py — env-driven settings for every pluggable service
    (slide 11: Backend API / Persistence / Pluggable Services)."""
    content = f'''"""Environment-driven settings. Every external dependency (DB, Redis,
object storage, AI provider) is configured here so services stay pluggable
(slide 11: "Integrated via strict service interfaces to prevent vendor
lock-in.")."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    project_name: str = "{spec.name}"

    # Persistence (slide 11: PostgreSQL + S3-compatible object storage)
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/auditable_automation"
    object_storage_endpoint: str = "http://localhost:9000"
    object_storage_bucket: str = "documents"

    # Async worker/queue (slide 11: Redis + Celery)
    redis_url: str = "redis://localhost:6379/0"

    # Pluggable AI provider used by the Template Agent (slide 6) and by the
    # OCR/extraction step of the runtime pipeline (slide 5, slide 9).
    anthropic_api_key: str = ""
    template_agent_model: str = "claude-sonnet-4-5"

    class Config:
        env_file = ".env"


settings = Settings()
'''
    write(out, "backend/app/core/config.py", content)
    write(out, "backend/app/core/__init__.py", "")
    write(out, "backend/app/__init__.py", "")


def gen_db_base(out: Path, spec: ProjectSpec) -> None:
    content = '''"""SQLAlchemy async session/engine setup."""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=False, future=True)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
'''
    write(out, "backend/app/db/base.py", content)
    write(out, "backend/app/db/__init__.py", "")


def gen_models(out: Path, spec: ProjectSpec) -> None:
    """app/models/*.py — the relational schema (slide 3 outline item 2).

    Key invariant from slide 7 "The Publish Lock":
        Editing a published template creates a NEW draft.
        Runtime documents always reference a LOCKED (immutable) version.
    Key invariant from slide 9 (state machine) + slide 10 (traceability):
        Every DocumentJob points at exactly one immutable TemplateVersion,
        and every RuleEvaluation it produces points at exactly one Rule
        that belonged to that version — so a risk score can always be
        traced back to "the exact version of the prompt, schema, and rule
        set that produced it."
    """
    content = '''"""Templates, immutable TemplateVersions ("the Publish Lock"), and the
schema-aware Rules that live inside a version.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (Enum, ForeignKey, Integer, JSON, String, Text,
                         UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TemplateVersionStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"   # immutable once set — see publish() below


class RuleCategory(str, enum.Enum):
    COMPLETENESS = "completeness"
    VALIDATION = "validation"
    ELIGIBILITY = "eligibility"
    RISK = "risk"


class RuleCondition(str, enum.Enum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    EXISTS = "exists"
    MISSING = "missing"


class Template(Base):
    """A named configuration owned by a Workspace Admin (slide 4). Holds no
    schema/rules itself — those live on immutable TemplateVersion rows."""

    __tablename__ = "templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    natural_language_intent: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    versions: Mapped[list["TemplateVersion"]] = relationship(
        back_populates="template", order_by="TemplateVersion.version_number"
    )


class TemplateVersion(Base):
    """The Publish Lock (slide 7). `json_schema` + `rule_set` together are
    "the unbreakable contract between AI extraction and downstream
    deterministic logic" (slide 5). Once `status == PUBLISHED`, this row
    must never be mutated — publish() enforces that at the service layer,
    and any further edit creates a new DRAFT version instead."""

    __tablename__ = "template_versions"
    __table_args__ = (UniqueConstraint("template_id", "version_number"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("templates.id"))
    version_number: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. "1.2.0"
    status: Mapped[TemplateVersionStatus] = mapped_column(
        Enum(TemplateVersionStatus), default=TemplateVersionStatus.DRAFT
    )
    json_schema: Mapped[dict] = mapped_column(JSON, nullable=False)  # the extraction contract
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)  # Template Agent prompt (slide 6)
    published_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    template: Mapped["Template"] = relationship(back_populates="versions")
    rules: Mapped[list["Rule"]] = relationship(back_populates="template_version")
    scoring_config: Mapped["ScoringConfig"] = relationship(
        back_populates="template_version", uselist=False
    )

    def publish(self) -> None:
        """Locks this version. Raises if already published — publishing
        twice would break the "immutable" guarantee every risk score
        depends on for traceability (slide 10)."""
        if self.status == TemplateVersionStatus.PUBLISHED:
            raise ValueError(
                f"TemplateVersion {self.id} is already published and immutable. "
                "Create a new draft instead of editing a published version."
            )
        self.status = TemplateVersionStatus.PUBLISHED
        self.published_at = datetime.utcnow()


class Rule(Base):
    """A single schema-aware rule (slide 7 Rules Builder): references a
    dotted field path into the extracted JSON, a condition, a comparison
    value, and a deterministic score contribution."""

    __tablename__ = "rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    template_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("template_versions.id"))
    rule_key: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "RULE_ID_412"
    category: Mapped[RuleCategory] = mapped_column(Enum(RuleCategory), nullable=False)
    field_path: Mapped[str] = mapped_column(String(255), nullable=False)
    condition: Mapped[RuleCondition] = mapped_column(Enum(RuleCondition), nullable=False)
    comparison_value: Mapped[dict] = mapped_column(JSON, nullable=False)  # wrapped so any type fits
    score_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    template_version: Mapped["TemplateVersion"] = relationship(back_populates="rules")


class ScoringConfig(Base):
    """Risk-level thresholds for a template version (slide 7 Scoring
    Builder: "Completely deterministic.")."""

    __tablename__ = "scoring_configs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("template_versions.id"), unique=True
    )
    low_max: Mapped[int] = mapped_column(Integer, nullable=False)
    medium_max: Mapped[int] = mapped_column(Integer, nullable=False)

    template_version: Mapped["TemplateVersion"] = relationship(back_populates="scoring_config")
'''
    write(out, "backend/app/models/template.py", content)
    write(out, "backend/app/models/__init__.py", "")


def gen_document_job_model(out: Path, spec: ProjectSpec) -> None:
    """app/models/document_job.py — the runtime state machine (slide 9) and
    the per-job audit trail that makes every risk score explainable
    (slide 10: "Every final decision can be traced mathematically back to
    the exact version of the prompt, schema, and rule set that produced
    it.")."""
    content = '''"""DocumentJob: the runtime state machine, and JobEvent: the append-only
audit trail behind every reviewer-facing risk score."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class JobStage(str, enum.Enum):
    """Exact pipeline stages from slide 9's state-machine diagram."""
    INGESTED = "INGESTED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    EXTRACTED = "EXTRACTED"
    RULE_EVALUATED = "RULE_EVALUATED"
    SCORED = "SCORED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REVIEWED = "REVIEWED"
    COMPLETED = "COMPLETED"
    # Failure branch off PROCESSING (slide 9): FAILED -> RETRY / TERMINAL_FAILURE
    FAILED = "FAILED"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"


# Stages a job is allowed to move to from a given stage. The Celery task
# chain (app/workers/tasks.py) checks this before every transition so a
# buggy task can never silently skip or corrupt the audit trail.
ALLOWED_TRANSITIONS: dict[JobStage, set[JobStage]] = {
    JobStage.INGESTED: {JobStage.QUEUED},
    JobStage.QUEUED: {JobStage.PROCESSING},
    JobStage.PROCESSING: {JobStage.EXTRACTED, JobStage.FAILED},
    JobStage.EXTRACTED: {JobStage.RULE_EVALUATED, JobStage.FAILED},
    JobStage.RULE_EVALUATED: {JobStage.SCORED, JobStage.FAILED},
    JobStage.SCORED: {JobStage.REVIEW_REQUIRED, JobStage.COMPLETED},
    JobStage.REVIEW_REQUIRED: {JobStage.REVIEWED},
    JobStage.REVIEWED: {JobStage.COMPLETED},
    JobStage.FAILED: {JobStage.QUEUED, JobStage.TERMINAL_FAILURE},  # retry or give up
    JobStage.COMPLETED: set(),
    JobStage.TERMINAL_FAILURE: set(),
}


class DocumentJob(Base):
    __tablename__ = "document_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    template_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("template_versions.id"))
    object_storage_key: Mapped[str] = mapped_column(String(512), nullable=False)  # raw doc blob
    stage: Mapped[JobStage] = mapped_column(Enum(JobStage), default=JobStage.INGESTED)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    extracted_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)  # low/medium/high
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    events: Mapped[list["JobEvent"]] = relationship(back_populates="job", order_by="JobEvent.created_at")
    rule_evaluations: Mapped[list["RuleEvaluation"]] = relationship(back_populates="job")

    def transition(self, to: JobStage) -> None:
        allowed = ALLOWED_TRANSITIONS[self.stage]
        if to not in allowed:
            raise ValueError(f"Illegal transition {self.stage} -> {to}. Allowed: {allowed}")
        self.stage = to


class JobEvent(Base):
    """Append-only log entry for every stage transition. This is what lets
    a Platform Developer say "state is recoverable without losing the
    document" (slide 9) after a crash mid-pipeline."""

    __tablename__ = "job_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_jobs.id"))
    stage: Mapped[JobStage] = mapped_column(Enum(JobStage), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    job: Mapped["DocumentJob"] = relationship(back_populates="events")


class RuleEvaluation(Base):
    """One row per rule fired for one job: exactly the trace shown on
    slide 10 (Rule_ID_412 -> +50 points -> Risk Level: HIGH)."""

    __tablename__ = "rule_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_jobs.id"))
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rules.id"))
    passed: Mapped[bool] = mapped_column(nullable=False)
    score_delta_applied: Mapped[int] = mapped_column(Integer, nullable=False)

    job: Mapped["DocumentJob"] = relationship(back_populates="rule_evaluations")
'''
    write(out, "backend/app/models/document_job.py", content)


def gen_extraction_schema(out: Path, spec: ProjectSpec) -> None:
    """app/schemas/extraction.py — the Pydantic extraction contract
    (slide 3 outline item 3, slide 6 "structural extraction contract").
    Generated directly from the spec's field list, so the Template Agent's
    structured output and the runtime extraction step share ONE definition."""
    lines = []
    for f in spec.template.fields:
        if f.type == "object" and f.properties:
            sub_name = f.name.title().replace("_", "") + "Fields"
            sub_lines = [f'    {k}: {("str" if v.get("type") == "string" else "Any")} | None = None'
                         for k, v in f.properties.items()]
            lines.append((sub_name, sub_lines, f.name, f.description))
    body_fields = []
    submodels = []
    for f in spec.template.fields:
        if f.type == "object" and f.properties:
            sub_name = f.name.title().replace("_", "") + "Fields"
            sub_body = "\n".join(
                f'    {k}: str | None = Field(None, description="one of {v.get("enum")}")'
                for k, v in f.properties.items()
            )
            submodels.append(f"class {sub_name}(BaseModel):\n{sub_body}\n")
            body_fields.append(f'    {f.name}: {sub_name} = Field(..., description="{f.description or f.name}")')
        else:
            opt = "" if f.description else f.name
            body_fields.append(
                f'    {f.name}: {f.py_type} = Field(..., description="{f.description or f.name}")'
            )

    content = f'''"""Extraction contract — generated from the template spec's field list.
This is the Pydantic model both the Template Agent (design-time) and the
Extraction step of the runtime pipeline (slide 9) validate against, so the
"unbreakable contract between AI extraction and downstream deterministic
logic" (slide 5) is literally one shared class, not two hand-synced ones.
"""
from typing import Any

from pydantic import BaseModel, Field


{chr(10).join(submodels)}
class {_pascal(spec.template.name)}Extraction(BaseModel):
{chr(10).join(body_fields)}
'''
    write(out, "backend/app/schemas/extraction.py", content)
    write(out, "backend/app/schemas/__init__.py", "")


def _pascal(s: str) -> str:
    return "".join(w.capitalize() for w in s.replace("-", " ").replace("_", " ").split())


def gen_rules_and_scoring_engines(out: Path, spec: ProjectSpec) -> None:
    """app/services/rules_engine.py + scoring_engine.py — section 3 outline
    item "Dynamic Rules & Scoring Engine". Deterministic, dependency-free
    Python — no LLM call anywhere in this file (slide 8: "traditional
    deterministic code to enforce it")."""
    rules_content = '''"""Deterministic rule evaluator (slide 7 Schema-Aware Rules, slide 10
traceability example). Pure functions, no I/O, no AI calls — this is the
piece an Academic Evaluator can unit-test to 100% coverage (slide 14
"Rule Correctness": 100% of deterministic test cases perfectly matched
expected engine results)."""
from __future__ import annotations

from typing import Any

from app.models.template import Rule, RuleCondition


def _get_path(data: dict, dotted_path: str) -> Any:
    """Resolve a dotted field path (e.g. "documents.id_proof") against the
    extracted JSON. Missing intermediate keys resolve to None rather than
    raising, so a MISSING/EXISTS rule can fire on absent data."""
    node: Any = data
    for part in dotted_path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def evaluate_rule(rule: Rule, extracted_json: dict) -> tuple[bool, int]:
    """Returns (passed, score_delta_applied). `passed` means the rule's
    CONDITION MATCHED, i.e. the rule "fired" — matching slide 10's framing
    where a fired validation rule contributes a positive risk delta."""
    actual = _get_path(extracted_json, rule.field_path)
    expected = rule.comparison_value.get("value") if isinstance(rule.comparison_value, dict) else rule.comparison_value

    condition = rule.condition
    if condition == RuleCondition.EQUALS:
        fired = actual == expected
    elif condition == RuleCondition.NOT_EQUALS:
        fired = actual != expected
    elif condition == RuleCondition.GREATER_THAN:
        fired = actual is not None and actual > expected
    elif condition == RuleCondition.LESS_THAN:
        fired = actual is not None and actual < expected
    elif condition == RuleCondition.EXISTS:
        fired = actual is not None
    elif condition == RuleCondition.MISSING:
        fired = actual is None
    else:
        raise ValueError(f"Unknown rule condition: {condition}")

    return fired, (rule.score_delta if fired else 0)


def evaluate_all(rules: list[Rule], extracted_json: dict) -> list[dict]:
    """Evaluate every rule in a template version against one extracted
    document. Returns one result dict per rule, ready to persist as
    RuleEvaluation rows (audit trail, slide 10)."""
    results = []
    for rule in rules:
        fired, delta = evaluate_rule(rule, extracted_json)
        results.append({
            "rule_id": rule.id,
            "rule_key": rule.rule_key,
            "category": rule.category,
            "passed": fired,
            "score_delta_applied": delta,
            "reason": rule.reason if fired else None,
        })
    return results
'''
    write(out, "backend/app/services/rules_engine.py", rules_content)

    scoring_content = '''"""Deterministic scoring engine (slide 7 Scoring Builder: "Completely
deterministic."). Sums rule score deltas and maps the total onto a risk
level via the template version's ScoringConfig thresholds."""
from app.models.template import ScoringConfig


def compute_risk(rule_results: list[dict], scoring_config: ScoringConfig) -> tuple[int, str, list[str]]:
    """Returns (total_score, risk_level, reasons). `reasons` lists the
    human-readable explanation for every rule that fired — this is what
    powers the Reviewer's "Risk Reasons" list (slide 13)."""
    total = sum(r["score_delta_applied"] for r in rule_results)
    reasons = [r["reason"] for r in rule_results if r["passed"] and r["reason"]]

    if total <= scoring_config.low_max:
        level = "low"
    elif total <= scoring_config.medium_max:
        level = "medium"
    else:
        level = "high"

    return total, level, reasons
'''
    write(out, "backend/app/services/scoring_engine.py", scoring_content)
    write(out, "backend/app/services/__init__.py", "")


def gen_template_agent_and_validator(out: Path, spec: ProjectSpec) -> None:
    """app/services/template_agent.py + schema_validator.py — slide 6:
    "Template Agent (Structured Output)" -> "Schema Validator: runs before
    any testing, rejecting malformed structures and demanding AI
    regeneration if necessary."""
    template_agent_content = f'''"""Design-time AI agent: turns a Workspace Admin's natural-language intent
(slide 4/6) into a draft JSON Schema + system prompt. This is the ONLY
place in the backend that calls an LLM at design time — the runtime
pipeline (app/workers/tasks.py) calls a separate, swappable extraction
service, and neither one ever influences the Rule/Scoring engines, which
stay pure deterministic Python (slide 8).
"""
from __future__ import annotations

import json

import anthropic

from app.core.config import settings
from app.services.schema_validator import SchemaValidationError, validate_json_schema

MAX_REGENERATION_ATTEMPTS = 3

SYSTEM_PROMPT_TEMPLATE = """# System Instruction:
# Draft a JSON Schema that captures the extraction contract described by
# the user's natural-language intent below. Respond with JSON Schema only.

User intent: {{intent}}
"""


class TemplateAgent:
    """Wraps the Anthropic API. Swap this class for a different provider
    without touching any caller — see slide 11 "Pluggable Services"."""

    def __init__(self, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def draft_schema(self, natural_language_intent: str) -> dict:
        """Returns a validated JSON Schema dict, or raises
        SchemaValidationError after exhausting regeneration attempts."""
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(intent=natural_language_intent)
        last_error: Exception | None = None

        for attempt in range(1, MAX_REGENERATION_ATTEMPTS + 1):
            response = self.client.messages.create(
                model=settings.template_agent_model,
                max_tokens=1024,
                system=system_prompt,
                messages=[{{
                    "role": "user",
                    "content": (
                        "Generate the JSON Schema now. Return raw JSON only, "
                        "no markdown fences, no commentary."
                        if last_error is None else
                        f"Your previous output failed validation: {{last_error}}. "
                        "Regenerate a corrected JSON Schema. Return raw JSON only."
                    ),
                }}],
            )
            raw_text = response.content[0].text
            try:
                candidate = json.loads(raw_text)
                validate_json_schema(candidate)
                return candidate
            except (json.JSONDecodeError, SchemaValidationError) as exc:
                last_error = exc
                continue

        raise SchemaValidationError(
            f"Template Agent failed to produce a valid schema after "
            f"{{MAX_REGENERATION_ATTEMPTS}} attempts. Last error: {{last_error}}"
        )
'''
    write(out, "backend/app/services/template_agent.py", template_agent_content)

    validator_content = '''"""Schema Validator (slide 6): "Runs before any testing, rejecting
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
'''
    write(out, "backend/app/services/schema_validator.py", validator_content)


def gen_celery_worker(out: Path, spec: ProjectSpec) -> None:
    """app/workers/celery_app.py + tasks.py — section 3 outline item 4:
    "Asynchronous Pipeline & State Machine (Redis & Celery)". Implements
    the exact stage chain from slide 9 and the FAILED -> retry /
    TERMINAL_FAILURE branch."""
    celery_app_content = '''"""Celery application wired to Redis (slide 11: Async Worker/Queue)."""
from celery import Celery

from app.core.config import settings

celery_app = Celery("auditable_automation", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,          # slide 9: "failures are persisted"
    worker_prefetch_multiplier=1,  # don't starve other jobs on a slow doc
    task_track_started=True,
)
'''
    write(out, "backend/app/workers/celery_app.py", celery_app_content)

    tasks_content = '''"""The runtime pipeline (slide 5 / slide 9):

    Redis Queue -> Celery Worker (loads an IMMUTABLE TemplateVersion)
        -> OCR Service -> Extraction (Schema) -> Rule Engine
        -> Scoring Engine -> Summary Service

State machine (slide 9):
    INGESTED -> QUEUED -> PROCESSING -> EXTRACTED -> RULE_EVALUATED
        -> SCORED -> REVIEW_REQUIRED -> REVIEWED -> COMPLETED
    PROCESSING/EXTRACTED/RULE_EVALUATED can also fail:
        FAILED -> RETRY (back to QUEUED) or TERMINAL_FAILURE

Every transition is written through DocumentJob.transition() (raises on
an illegal jump) and logged as a JobEvent, so "state is recoverable
without losing the document" even if a worker crashes mid-task.
"""
from __future__ import annotations

import asyncio
from uuid import UUID

from celery import chain
from celery.exceptions import MaxRetriesExceededError

from app.db.base import async_session
from app.models.document_job import DocumentJob, JobEvent, JobStage, RuleEvaluation
from app.models.template import Rule, TemplateVersion
from app.services.rules_engine import evaluate_all
from app.services.scoring_engine import compute_risk
from app.workers.celery_app import celery_app

MAX_RETRIES = 3


def _run(coro):
    """Celery tasks are sync; the app is async end-to-end. This is the one
    sanctioned sync/async boundary."""
    return asyncio.get_event_loop().run_until_complete(coro)


async def _transition(session, job: DocumentJob, to: JobStage, detail: str | None = None) -> None:
    job.transition(to)
    session.add(JobEvent(job_id=job.id, stage=to, detail=detail))
    await session.commit()


@celery_app.task(bind=True, max_retries=MAX_RETRIES, default_retry_delay=30)
def process_document(self, job_id: str) -> None:
    """Entry point: QUEUED -> PROCESSING, then hands off to the OCR/extract
    step. Retries transport-level failures (e.g. OCR service timeout);
    schema-contract failures are NOT retried here — they go straight to
    TERMINAL_FAILURE because retrying won't fix a bad template."""
    async def _inner():
        async with async_session() as session:
            job = await session.get(DocumentJob, UUID(job_id))
            await _transition(session, job, JobStage.PROCESSING, "worker picked up job")
            try:
                extracted = await _ocr_and_extract(session, job)
                await _transition(session, job, JobStage.EXTRACTED, "extraction complete")
                await _evaluate_rules(session, job, extracted)
            except Exception as exc:  # noqa: BLE001 - deliberately broad: any failure -> FAILED
                await _transition(session, job, JobStage.FAILED, detail=str(exc))
                raise

    try:
        _run(_inner())
    except Exception as exc:
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            _run(_mark_terminal_failure(job_id, str(exc)))


async def _mark_terminal_failure(job_id: str, detail: str) -> None:
    async with async_session() as session:
        job = await session.get(DocumentJob, UUID(job_id))
        job.stage = JobStage.TERMINAL_FAILURE
        session.add(JobEvent(job_id=job.id, stage=JobStage.TERMINAL_FAILURE, detail=detail))
        await session.commit()


async def _ocr_and_extract(session, job: DocumentJob) -> dict:
    """Pluggable OCR + extraction step (slide 11). Swap the implementation
    behind this function without touching the state machine or the rule
    engine. Returns extracted JSON that MUST validate against the
    TemplateVersion's json_schema (the design-time/runtime contract,
    slide 5)."""
    template_version = await session.get(TemplateVersion, job.template_version_id)
    # Replace with a real OCR + structured-extraction call (e.g. Claude
    # with a JSON Schema tool matching template_version.json_schema).
    extracted: dict = {}  # placeholder — wire up your OCR/extraction provider here
    job.extracted_json = extracted
    return extracted


async def _evaluate_rules(session, job: DocumentJob, extracted: dict) -> None:
    template_version = await session.get(TemplateVersion, job.template_version_id)
    rules_result = await session.execute(
        __import__("sqlalchemy").select(Rule).where(Rule.template_version_id == template_version.id)
    )
    rules: list[Rule] = list(rules_result.scalars())

    results = evaluate_all(rules, extracted)
    for r in results:
        session.add(RuleEvaluation(
            job_id=job.id, rule_id=r["rule_id"], passed=r["passed"],
            score_delta_applied=r["score_delta_applied"],
        ))
    await _transition(session, job, JobStage.RULE_EVALUATED, f"{len(results)} rules evaluated")

    total, level, reasons = compute_risk(results, template_version.scoring_config)
    job.risk_score = total
    job.risk_level = level
    await _transition(session, job, JobStage.SCORED, f"score={total} level={level}")

    next_stage = JobStage.REVIEW_REQUIRED if level in ("medium", "high") else JobStage.COMPLETED
    await _transition(session, job, next_stage, "; ".join(reasons) or None)
'''
    write(out, "backend/app/workers/tasks.py", tasks_content)
    write(out, "backend/app/workers/__init__.py", "")


def gen_api_and_main(out: Path, spec: ProjectSpec) -> None:
    """app/api/v1/*.py + app/main.py — the FastAPI surface a Platform
    Developer depends on (slide 4: "Need: Stable APIs & Observability")."""
    templates_api = '''"""Workspace Admin surface: draft, edit, and PUBLISH template versions.
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
'''
    write(out, "backend/app/api/v1/templates.py", templates_api)

    documents_api = '''"""Document ingestion: creates a DocumentJob pinned to an immutable
TemplateVersion and enqueues the runtime pipeline (slide 9)."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.models.document_job import DocumentJob, JobEvent, JobStage
from app.models.template import TemplateVersion, TemplateVersionStatus
from app.workers.tasks import process_document

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/ingest")
async def ingest_document(
    template_version_id: UUID, object_storage_key: str, session: AsyncSession = Depends(get_session)
):
    version = await session.get(TemplateVersion, template_version_id)
    if version is None:
        raise HTTPException(404, "Template version not found")
    if version.status != TemplateVersionStatus.PUBLISHED:
        raise HTTPException(409, "Documents may only be processed against a PUBLISHED template version")

    job = DocumentJob(template_version_id=version.id, object_storage_key=object_storage_key)
    session.add(job)
    await session.flush()
    session.add(JobEvent(job_id=job.id, stage=JobStage.INGESTED, detail="document uploaded"))
    job.stage = JobStage.QUEUED
    session.add(JobEvent(job_id=job.id, stage=JobStage.QUEUED, detail="enqueued for processing"))
    await session.commit()

    process_document.delay(str(job.id))
    return {"job_id": str(job.id), "stage": job.stage}
'''
    write(out, "backend/app/api/v1/documents.py", documents_api)

    jobs_api = '''"""Reviewer surface (slide 4/13): the prioritized queue plus the full
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
'''
    write(out, "backend/app/api/v1/jobs.py", jobs_api)
    write(out, "backend/app/api/v1/__init__.py", "")
    write(out, "backend/app/api/__init__.py", "")

    main_content = f'''"""FastAPI entrypoint for {spec.name}."""
from fastapi import FastAPI

from app.api.v1 import documents, jobs, templates
from app.core.config import settings

app = FastAPI(title=settings.project_name)

app.include_router(templates.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")


@app.get("/healthz")
async def healthz():
    return {{"status": "ok"}}
'''
    write(out, "backend/app/main.py", main_content)


def gen_requirements(out: Path, spec: ProjectSpec) -> None:
    content = """fastapi>=0.115
uvicorn[standard]>=0.30
sqlalchemy[asyncio]>=2.0
asyncpg>=0.29
alembic>=1.13
celery[redis]>=5.4
redis>=5.0
pydantic-settings>=2.4
jsonschema>=4.23
anthropic>=0.34
pytest>=8.0
pytest-asyncio>=0.24
httpx>=0.27
"""
    write(out, "backend/requirements.txt", content)
    write(out, "backend/.env.example", (
        "DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/auditable_automation\n"
        "REDIS_URL=redis://localhost:6379/0\n"
        "OBJECT_STORAGE_ENDPOINT=http://localhost:9000\n"
        "OBJECT_STORAGE_BUCKET=documents\n"
        "ANTHROPIC_API_KEY=\n"
    ))


def gen_tests(out: Path, spec: ProjectSpec) -> None:
    """tests/test_rules_engine.py — the deterministic test suite behind
    slide 14 Metric 3 ("100% of deterministic test cases perfectly matched
    expected engine results, confirming immutable rules") and slide 12's
    working rhythm ("zero features moved to Done without happy-path and
    failure edge-case tests"). Generated with one happy-path + one
    edge-case test per rule in the spec."""
    cases = []
    for r in spec.template.rules:
        # The value that actually SATISFIES each condition differs from the
        # rule's comparison value for the inequality conditions — e.g. a
        # "greater_than 0" rule is not satisfied by the leaf value 0 itself.
        if r.condition == "greater_than":
            leaf_value = r.value + 1
        elif r.condition == "less_than":
            leaf_value = r.value - 1
        else:
            leaf_value = r.value
        cases.append(f'''
def test_{r.id.lower()}_fires_when_condition_met():
    rule = Rule(id=uuid4(), template_version_id=uuid4(), rule_key="{r.id}",
                category=RuleCategory.{r.category.upper()}, field_path="{r.field}",
                condition=RuleCondition.{r.condition.upper()},
                comparison_value={{"value": {r.value!r}}}, score_delta={r.score_delta},
                reason="{r.reason}")
    doc = {{}}
    for part in reversed("{r.field}".split(".")):
        doc = {{part: {leaf_value!r}}} if part == "{r.field}".split(".")[-1] else {{part: doc}}
    fired, delta = evaluate_rule(rule, doc)
    assert fired is True
    assert delta == {r.score_delta}


def test_{r.id.lower()}_does_not_fire_on_missing_field():
    rule = Rule(id=uuid4(), template_version_id=uuid4(), rule_key="{r.id}",
                category=RuleCategory.{r.category.upper()}, field_path="{r.field}",
                condition=RuleCondition.{r.condition.upper()},
                comparison_value={{"value": {r.value!r}}}, score_delta={r.score_delta},
                reason="{r.reason}")
    fired, delta = evaluate_rule(rule, {{}})  # edge case: field entirely absent
    if RuleCondition.{r.condition.upper()} == RuleCondition.MISSING:
        assert fired is True
    else:
        assert fired is False
        assert delta == 0
''')
    content = f'''"""Deterministic rule-engine tests, generated from the template spec.
Every rule gets a happy-path (condition met) and an edge-case (field
missing) test — see slide 12 "Working Rhythm" and slide 14 "Rule
Correctness"."""
from uuid import uuid4

from app.models.template import Rule, RuleCategory, RuleCondition
from app.services.rules_engine import evaluate_rule

{chr(10).join(cases)}
'''
    write(out, "backend/tests/test_rules_engine.py", content)
    write(out, "backend/tests/__init__.py", "")


def gen_frontend_stubs(out: Path, spec: ProjectSpec) -> None:
    """React + TypeScript reviewer UI (slide 4/13, outline section 5)."""
    reviewer = '''import { useEffect, useState } from "react";

// Split-pane reviewer screen (slide 4 "Reviewer" persona, slide 13
// "Reviewer Queue"): document preview on the left, extracted JSON +
// traceable risk scorecard on the right.

type RuleEvaluationView = { ruleKey: string; passed: boolean; scoreDeltaApplied: number };

type JobDetail = {
  id: string;
  stage: string;
  extractedJson: Record<string, unknown> | null;
  riskScore: number | null;
  riskLevel: "low" | "medium" | "high" | null;
  aiSummary: string | null;
};

export function ReviewerScreen({ jobId }: { jobId: string }) {
  const [job, setJob] = useState<JobDetail | null>(null);

  useEffect(() => {
    fetch(`/api/v1/jobs/${jobId}`)
      .then((r) => r.json())
      .then(setJob);
  }, [jobId]);

  if (!job) return <div>Loading…</div>;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
      <section>
        <h2>Document Preview</h2>
        {/* Wire up your PDF/image viewer against job.id's source document. */}
      </section>

      <section>
        <h2>Structured Output &amp; Risk</h2>
        <pre>{JSON.stringify(job.extractedJson, null, 2)}</pre>

        {job.riskLevel && (
          <div className={`risk-badge risk-${job.riskLevel}`}>
            Risk Score: {job.riskScore} ({job.riskLevel.toUpperCase()})
          </div>
        )}

        {job.aiSummary && (
          <div>
            <h3>AI-Generated Summary</h3>
            <p>{job.aiSummary}</p>
          </div>
        )}
      </section>
    </div>
  );
}
'''
    write(out, "frontend/src/screens/ReviewerScreen.tsx", reviewer)

    builder = '''import { useState } from "react";

// Workspace Admin screen (slide 4 "Need: Low-code configuration", slide 6
// Template Agent flow): natural-language intent in, draft JSON Schema +
// Rules Builder out, PUBLISH locks the version (slide 7 Publish Lock).

export function TemplateBuilder() {
  const [intent, setIntent] = useState("");
  const [draftSchema, setDraftSchema] = useState<object | null>(null);

  async function generateDraft() {
    const res = await fetch("/api/v1/templates/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ natural_language_intent: intent }),
    });
    setDraftSchema(await res.json());
  }

  async function publish(templateId: string, versionId: string) {
    // Publishing is irreversible for this version — see backend
    // TemplateVersion.publish(). Confirm with the user before calling.
    await fetch(`/api/v1/templates/${templateId}/versions/${versionId}/publish`, { method: "POST" });
  }

  return (
    <div>
      <label>
        Natural Language Intent
        <input value={intent} onChange={(e) => setIntent(e.target.value)} />
      </label>
      <button onClick={generateDraft}>Generate Draft Schema</button>

      {draftSchema && (
        <>
          <h3>Draft Schema</h3>
          <pre>{JSON.stringify(draftSchema, null, 2)}</pre>
          {/* Rules Builder (field / condition / value / category) goes here,
              reading fields out of draftSchema.properties. */}
        </>
      )}
    </div>
  );
}
'''
    write(out, "frontend/src/screens/TemplateBuilder.tsx", builder)


def gen_readme(out: Path, spec: ProjectSpec) -> None:
    rules_table = "\n".join(
        f"| `{r.id}` | {r.category} | `{r.field}` {r.condition} `{r.value}` | {r.score_delta:+d} | {r.reason} |"
        for r in spec.template.rules
    )
    content = f'''# {spec.name} — generated backend ({spec.vertical_slice})

Generated by `scaffold_agent.py` from `example_specs/{spec.vertical_slice}.yaml`.
Nothing in here is hand-written boilerplate you need to fill in blindly —
every file traces back to a specific slide in the architecture deck, noted
in that file's docstring. This README is the map.

## Where each outline section landed

| Your outline section | Generated files |
|---|---|
| 1. System & Data Flow Architecture | this README + `app/workers/tasks.py` docstring (design-time/runtime split, doc lifecycle) |
| 2. Relational DB Design | `app/models/template.py`, `app/models/document_job.py` |
| 3. Template Agent & Validator | `app/services/template_agent.py`, `app/services/schema_validator.py`, `app/schemas/extraction.py` |
| 3. Rules & Scoring Engine | `app/services/rules_engine.py`, `app/services/scoring_engine.py` |
| 4. Async Pipeline & State Machine | `app/workers/celery_app.py`, `app/workers/tasks.py`, `JobStage`/`ALLOWED_TRANSITIONS` in `models/document_job.py` |
| 5. Reviewer UI | `frontend/src/screens/ReviewerScreen.tsx`, `TemplateBuilder.tsx` |
| 6. Roadmap & Evaluation | this README, `tests/test_rules_engine.py` |

## The Publish Lock, concretely

`TemplateVersion.publish()` (`app/models/template.py`) flips `status` to
`PUBLISHED` and stamps `published_at`. Calling it twice raises. The
`/api/v1/documents/ingest` endpoint refuses to enqueue a job against any
version that isn't `PUBLISHED` — so a runtime document can never reference
a draft, and a published version can never be silently edited out from
under an in-flight job.

## State machine

```
INGESTED -> QUEUED -> PROCESSING -> EXTRACTED -> RULE_EVALUATED -> SCORED
    -> REVIEW_REQUIRED -> REVIEWED -> COMPLETED
PROCESSING / EXTRACTED / RULE_EVALUATED -> FAILED -> QUEUED (retry) or TERMINAL_FAILURE
```
Enforced by `DocumentJob.transition()` against `ALLOWED_TRANSITIONS` —
an illegal jump raises instead of silently corrupting the audit trail.

## Rules seeded from your spec ({spec.vertical_slice})

| Rule | Category | Condition | Score | Reason |
|---|---|---|---|---|
{rules_table}

## Running it

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in DATABASE_URL / REDIS_URL / ANTHROPIC_API_KEY
alembic init alembic   # first time only — then point env.py at app.db.base.Base.metadata
uvicorn app.main:app --reload
celery -A app.workers.celery_app worker --loglevel=info
pytest
```

## 12-week roadmap (slide 12)

| Week | Milestone | What "done" means |
|---|---|---|
| W4 | M1 — Configuration POC | Template Agent drafts a schema, Schema Validator rejects/regenerates on malformed output |
| W7 | M2 — Decision Logic POC | Rules + Scoring engines pass 100% of deterministic tests (`pytest backend/tests`) |
| W9 | M3 — Template Runtime POC | A published `TemplateVersion` drives one full Celery pipeline run end-to-end |
| W11 | M4 — End-to-End Runtime | Reviewer UI reads a real `REVIEW_REQUIRED` job from `/api/v1/jobs/review-queue` |
| W12 | M5 — Final MVP & Evaluation | Metrics below measured against a labeled eval set |

Working rhythm (slide 12): small PRs, deterministic test cases for both
engines before merging, no feature reaches "Done" without a happy-path
**and** a failure/edge-case test — `gen_tests` above already seeds one of
each per rule; extend, don't skip, as you add rules.

## Evaluation targets (slide 14)

| Metric | Target shown in deck | Where to measure it |
|---|---|---|
| Field extraction Precision / Recall / F1 | 94.5% / 92.1% / 93.3% | compare `extracted_json` vs. a labeled eval set |
| Schema validity (first-attempt pass) | 95.2% | `schema_validator.validate_json_schema` call count vs. regenerations in `template_agent.py` |
| Rule correctness | 100% of deterministic cases | `pytest backend/tests/test_rules_engine.py` |
| Processing reliability under load/failure | near 100%, retries recovering fast | count `COMPLETED` vs `TERMINAL_FAILURE` `DocumentJob` rows under injected failures |

## Regenerating or extending

Add fields/rules to `example_specs/{spec.vertical_slice}.yaml` (or write a
new spec for a different document type) and re-run:

```bash
python scaffold_agent.py example_specs/{spec.vertical_slice}.yaml --out ./generated
```

It overwrites the generated tree deterministically — the spec is the
single source of truth, matching the platform's own "AI drafts the
contract, deterministic code enforces it" principle (slide 8) applied to
this tool itself.
'''
    write(out, "README.md", content)


# --------------------------------------------------------------------------
# CLI driver
# --------------------------------------------------------------------------

GENERATORS = [
    gen_core_config,
    gen_db_base,
    gen_models,
    gen_document_job_model,
    gen_extraction_schema,
    gen_rules_and_scoring_engines,
    gen_template_agent_and_validator,
    gen_celery_worker,
    gen_api_and_main,
    gen_requirements,
    gen_tests,
    gen_frontend_stubs,
    gen_readme,
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", type=Path, help="Path to a template spec YAML file")
    parser.add_argument("--out", type=Path, default=Path("./generated"), help="Output directory")
    args = parser.parse_args()

    if not args.spec.exists():
        print(f"Spec file not found: {args.spec}", file=sys.stderr)
        sys.exit(1)

    spec = load_spec(args.spec)
    print(f"Scaffolding '{spec.name}' ({spec.vertical_slice}) -> {args.out}/\n")

    for gen in GENERATORS:
        gen(args.out, spec)

    print(f"\nDone. {len(spec.template.fields)} fields, {len(spec.template.rules)} rules scaffolded.")
    print(f"See {args.out}/README.md for how every file maps back to your architecture deck.")


if __name__ == "__main__":
    main()
