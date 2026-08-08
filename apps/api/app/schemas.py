from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


ChangeOperation = Literal[
    "CREATE_DOCUMENT", "ADD_BLOCK", "UPDATE_BLOCK", "MOVE_BLOCK",
    "ADD_RELATION", "MARK_DUPLICATE", "REPORT_CONFLICT", "UPDATE_DOCUMENT",
]


class SendVerificationCodeRequest(BaseModel):
    email: EmailStr


class CodeLoginRequest(BaseModel):
    email: EmailStr
    verification_code: str = Field(pattern=r"^\d{6}$")


class User(BaseModel):
    id: str
    email: EmailStr
    display_name: str


class IngestionCreate(BaseModel):
    kind: Literal["text"] = "text"
    content: str = Field(min_length=2, max_length=100_000)
    title: str | None = Field(default=None, max_length=160)


class SourceProcessingError(BaseModel):
    code: str
    message: str
    retryable: bool
    requires_reupload: bool


class InputCoverage(BaseModel):
    input_index: int = Field(ge=0)
    knowledge_unit_count: int = Field(ge=0)


class SourceProcessing(BaseModel):
    source_id: str
    status: Literal["received", "processing", "proposed", "failed"]
    stage: Literal[
        "queued", "ocr", "extracting", "coverage_repair",
        "retrieving", "planning", "complete", "failed",
    ]
    processed_inputs: int = Field(ge=0)
    total_inputs: int = Field(ge=0)
    covered_inputs: int = Field(ge=0)
    input_coverage: list[InputCoverage]
    extraction_attempts: int = Field(ge=0, le=2)
    change_set_id: str | None = None
    error: SourceProcessingError | None = None


class ReprocessSource(BaseModel):
    instruction: str | None = Field(default=None, max_length=2000)

    @field_validator("instruction")
    @classmethod
    def normalize_instruction(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None


class ChangeItem(BaseModel):
    id: str
    operation: ChangeOperation
    target_document_id: str | None = None
    target_title: str
    before_title: str | None = None
    reason: str
    before: str | None = None
    after: str
    evidence: str
    confidence: float = Field(ge=0, le=1)
    accepted: bool | None = None


class ChangeSource(BaseModel):
    title: str | None = None
    content: str


class ChangeSet(BaseModel):
    id: str
    source_id: str | None = None
    origin: Literal["ai_ingestion", "manual_edit"]
    status: Literal["proposed", "applied", "partially_applied", "rejected", "superseded"]
    summary: str
    supersedes_change_set_id: str | None = None
    analysis_instruction: str | None = None
    created_at: datetime
    source: ChangeSource | None = None
    items: list[ChangeItem]


class ApplyChangeSet(BaseModel):
    accepted_item_ids: list[str] | None = None


class Document(BaseModel):
    id: str
    title: str
    markdown: str
    version: int
    created_at: datetime
    updated_at: datetime


class DocumentVersion(BaseModel):
    version: int
    title: str
    markdown: str
    reason: str
    created_at: datetime


class DocumentUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    markdown: str = Field(min_length=1, max_length=100_000)
    base_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=300)

    @field_validator("title", "markdown")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class KnowledgeEvent(BaseModel):
    id: str
    change_set_id: str
    created_at: datetime
    title: str
    summary: str
    affected_documents: list[str]
    accepted_count: int
    rejected_count: int
    origin: Literal["ai_ingestion", "manual_edit"]
