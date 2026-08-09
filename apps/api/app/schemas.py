from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


ChangeOperation = Literal[
    "CREATE_DOCUMENT", "ADD_BLOCK", "UPDATE_BLOCK", "MOVE_BLOCK",
    "ADD_RELATION", "MARK_DUPLICATE", "REPORT_CONFLICT", "UPDATE_DOCUMENT",
]


class SendVerificationCodeRequest(BaseModel):
    email: EmailStr


class CodeLoginRequest(BaseModel):
    email: EmailStr
    verification_code: str = Field(pattern=r"^\d{6}$")


class AdminLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class User(BaseModel):
    id: str
    email: EmailStr
    display_name: str
    role: Literal["user", "admin"] = "user"


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
    visibility: Literal["private", "public"] = "private"


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


MemoryKind = Literal["style", "topic_split", "domain", "naming", "merge_preference"]
MemoryScope = Literal["global", "document", "topic"]
MemoryStatus = Literal["active", "candidate", "suppressed"]
MemoryOrigin = Literal["user_explicit", "ai_inferred", "ai_observed"]


class Memory(BaseModel):
    id: str
    kind: MemoryKind
    content: str
    scope: MemoryScope
    scope_ref: str | None
    status: MemoryStatus
    confidence: float = Field(ge=0, le=1)
    origin: MemoryOrigin
    use_count: int = Field(ge=0)
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: MemoryKind
    content: str = Field(min_length=1, max_length=2000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Memory content cannot be blank")
        return value


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(default=None, min_length=1, max_length=2000)
    status: MemoryStatus | None = None

    @field_validator("content")
    @classmethod
    def normalize_optional_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Memory content cannot be blank")
        return value

    @model_validator(mode="after")
    def require_change(self):
        if self.content is None and self.status is None:
            raise ValueError("At least one memory field must be provided")
        return self


class InferredMemory(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: MemoryKind
    content: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0.6, le=1.0)
    reason: str = Field(min_length=1, max_length=1000)


class MemoryInferenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    memories: list[InferredMemory] = Field(default_factory=list, max_length=10)


ChatGrounding = Literal["knowledge", "knowledge_plus_general", "general", "insufficient"]
ChatMessageStatus = Literal["generating", "completed", "failed", "cancelled"]


class ChatSession(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ChatSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="新对话", min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Chat title cannot be blank")
        return value


class ChatSessionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Chat title cannot be blank")
        return value


class ChatMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=4000)
    include_public: bool = True

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Chat message cannot be blank")
        return value


class ChatCitation(BaseModel):
    ref: str
    document_id: str
    title: str
    excerpt: str
    visibility: Literal["private", "public"] = "private"
    chunk_id: str | None = None
    document_version: int | None = None
    retrieval_mode: Literal["hybrid", "keyword", "empty"] | None = None


class ChatMessage(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant"]
    status: ChatMessageStatus
    content: str
    model: str | None
    grounding: ChatGrounding | None
    citations: list[ChatCitation]
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None
    include_public: bool = True


class SearchItem(BaseModel):
    document_id: str
    title: str
    excerpt: str
    document_version: int
    chunk_id: str
    matching_mode: Literal["hybrid", "keyword", "empty"]
    score: float
    visibility: Literal["private", "public"] = "private"


class SearchResponse(BaseModel):
    items: list[SearchItem]
    retrieval_mode: Literal["hybrid", "keyword", "empty"]
    fallback_reason: str | None = None


class AdminUser(BaseModel):
    id: str
    email: EmailStr
    username: str | None
    display_name: str
    role: Literal["user", "admin"]
    status: Literal["active", "disabled"]
    document_count: int = Field(ge=0)
    public_document_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class KnowledgeOwnership(BaseModel):
    id: str
    user_id: str
    owner_email: EmailStr
    owner_display_name: str
    title: str
    version: int
    visibility: Literal["private", "public"]
    created_at: datetime
    updated_at: datetime


class PublicDocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    markdown: str = Field(min_length=1, max_length=100_000)

    @field_validator("title", "markdown")
    @classmethod
    def reject_blank_public_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class ReindexResponse(BaseModel):
    document_id: str
    chunks: int
    status: Literal["completed"]
