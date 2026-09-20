"""Extraction contract — generated from the template spec's field list.
This is the Pydantic model both the Template Agent (design-time) and the
Extraction step of the runtime pipeline (slide 9) validate against, so the
"unbreakable contract between AI extraction and downstream deterministic
logic" (slide 5) is literally one shared class, not two hand-synced ones.
"""
from typing import Any

from pydantic import BaseModel, Field


class DocumentsFields(BaseModel):
    id_proof: str | None = Field(None, description="one of ['verified', 'missing']")
    contract: str | None = Field(None, description="one of ['signed', 'unsigned']")

class EmployeeOnboardingTemplateExtraction(BaseModel):
    employee_id: str = Field(..., description="Unique ID")
    first_name: str = Field(..., description="first_name")
    last_name: str = Field(..., description="last_name")
    department: str = Field(..., description="department")
    start_date: str = Field(..., description="start_date")
    documents: DocumentsFields = Field(..., description="documents")
    salary_amount: float = Field(..., description="salary_amount")
