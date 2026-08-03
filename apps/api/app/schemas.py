from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


ChangeOperation = Literal[
    "CREATE_DOCUMENT", "ADD_BLOCK", "UPDATE_BLOCK", "MOVE_BLOCK",
    "ADD_RELATION", "MARK_DUPLICATE", "REPORT_CONFLICT",
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


class ChangeItem(BaseModel):
    id: str
    operation: ChangeOperation
    target_document_id: str | None = None
    target_title: str
    reason: str
    before: str | None = None
    after: str
    evidence: str
    confidence: float = Field(ge=0, le=1)


class ChangeSet(BaseModel):
    id: str
    source_id: str
    status: Literal["proposed", "applied", "partially_applied", "rejected"]
    summary: str
    created_at: datetime
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


class KnowledgeEvent(BaseModel):
    id: str
    change_set_id: str
    created_at: datetime
    title: str
    summary: str
    affected_documents: list[str]
    accepted_count: int
    rejected_count: int
