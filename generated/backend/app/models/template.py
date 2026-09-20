"""Templates, immutable TemplateVersions ("the Publish Lock"), and the
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
    document_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
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
