import hmac
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index,
    Integer, MetaData, REAL, String, Table, Text, TypeDecorator, UniqueConstraint, create_engine,
    case, delete, func, insert, select, update,
)
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from .ai import ExtractionResult, MergeProposal


logger = logging.getLogger("nerva.store")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


metadata = MetaData()
LEGACY_USER_ID = "usr_legacy_local_migration"


class EmbeddingVector(TypeDecorator):
    """PostgreSQL REAL[] with JSON storage for the SQLite test store."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(REAL, dimensions=1, as_tuple=False))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return [float(item) for item in value]

users = Table(
    "users", metadata,
    Column("id", String(40), primary_key=True),
    Column("email", String(320), nullable=False, unique=True),
    Column("username", String(80)),
    Column("display_name", String(80), nullable=False),
    Column("password_hash", Text),
    Column("role", String(20), nullable=False, server_default="user"),
    Column("status", String(20), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
    CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),
)

sessions = Table(
    "sessions", metadata,
    Column("id", String(40), primary_key=True),
    Column("user_id", String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
)

email_verification_codes = Table(
    "email_verification_codes", metadata,
    Column("id", String(40), primary_key=True),
    Column("email", String(320), nullable=False),
    Column("code_hash", String(64), nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("resend_after", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("consumed_at", DateTime(timezone=True)),
    CheckConstraint("attempts >= 0", name="ck_email_codes_attempts"),
)

sources = Table(
    "sources", metadata,
    Column("id", String(40), primary_key=True),
    Column("user_id", String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("kind", String(30), nullable=False),
    Column("title", String(160)),
    Column("content", Text, nullable=False),
    Column("processing_status", String(30), nullable=False),
    Column("ai_provider", String(40)),
    Column("ai_model", String(160)),
    Column("prompt_version", String(80)),
    Column("error_code", String(80)),
    Column("error_message", Text),
    Column("processing_stage", String(30), nullable=False, server_default="queued"),
    Column("processing_started_at", DateTime(timezone=True)),
    Column("total_inputs", Integer, nullable=False, server_default="0"),
    Column("processed_inputs", Integer, nullable=False, server_default="0"),
    Column("covered_inputs", Integer, nullable=False, server_default="0"),
    Column("extraction_attempts", Integer, nullable=False, server_default="0"),
    Column(
        "pending_supersedes_change_set_id", String(40),
        ForeignKey(
            "change_sets.id", ondelete="SET NULL",
            name="fk_sources_pending_supersedes", use_alter=True,
        ),
    ),
    Column("pending_analysis_instruction", Text),
    Column("ocr_model", String(160)),
    Column("ocr_prompt_version", String(80)),
    Column("processed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "processing_status IN ('received', 'processing', 'proposed', 'failed')",
        name="ck_sources_processing_status",
    ),
    CheckConstraint(
        "processing_stage IN ('queued', 'ocr', 'extracting', 'coverage_repair', 'retrieving', 'planning', 'complete', 'failed')",
        name="ck_sources_processing_stage",
    ),
    CheckConstraint("total_inputs >= 0", name="ck_sources_total_inputs"),
    CheckConstraint("covered_inputs >= 0 AND covered_inputs <= total_inputs", name="ck_sources_covered_inputs"),
    CheckConstraint("extraction_attempts >= 0 AND extraction_attempts <= 2", name="ck_sources_extraction_attempts"),
    CheckConstraint(
        "processed_inputs >= 0 AND processed_inputs <= total_inputs",
        name="ck_sources_processed_inputs",
    ),
)

knowledge_units = Table(
    "knowledge_units", metadata,
    Column("id", String(40), primary_key=True),
    Column("user_id", String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("source_id", String(40), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
    Column("input_index", Integer, nullable=False, server_default="0"),
    Column("type", String(40), nullable=False),
    Column("subject", String(160), nullable=False),
    Column("content", Text, nullable=False),
    Column("source_span", Text, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_knowledge_units_confidence"),
    CheckConstraint("input_index >= 0", name="ck_knowledge_units_input_index"),
)

documents = Table(
    "documents", metadata,
    Column("id", String(40), primary_key=True),
    Column("user_id", String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("title", String(160), nullable=False),
    Column("markdown", Text, nullable=False),
    Column("visibility", String(20), nullable=False, server_default="private"),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("version >= 1", name="ck_documents_version"),
    CheckConstraint("visibility IN ('private', 'public')", name="ck_documents_visibility"),
)

document_chunks = Table(
    "document_chunks", metadata,
    Column("id", String(40), primary_key=True),
    Column("user_id", String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("document_id", String(40), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
    Column("document_version", Integer, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("content", Text, nullable=False),
    Column("embedding", EmbeddingVector),
    Column("embedding_model", String(160)),
    Column("embedding_status", String(20), nullable=False, server_default="pending"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("document_version >= 1", name="ck_document_chunks_version"),
    CheckConstraint("ordinal >= 0", name="ck_document_chunks_ordinal"),
    CheckConstraint(
        "embedding_status IN ('pending', 'ready', 'failed')",
        name="ck_document_chunks_embedding_status",
    ),
    UniqueConstraint(
        "document_id", "document_version", "ordinal",
        name="uq_document_chunks_document_version_ordinal",
    ),
)

document_versions = Table(
    "document_versions", metadata,
    Column("id", String(40), primary_key=True),
    Column("user_id", String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("document_id", String(40), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("title", String(160), nullable=False),
    Column("markdown", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("version >= 1", name="ck_document_versions_version"),
    UniqueConstraint("document_id", "version", name="uq_document_version"),
)

change_sets = Table(
    "change_sets", metadata,
    Column("id", String(40), primary_key=True),
    Column("user_id", String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("source_id", String(40), ForeignKey("sources.id", ondelete="RESTRICT")),
    Column("origin", String(30), nullable=False),
    Column("status", String(30), nullable=False),
    Column("summary", Text, nullable=False),
    Column("supersedes_change_set_id", String(40), ForeignKey("change_sets.id", ondelete="SET NULL")),
    Column("analysis_instruction", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "status IN ('proposed', 'applied', 'partially_applied', 'rejected', 'superseded')",
        name="ck_change_sets_status",
    ),
    CheckConstraint(
        "origin IN ('ai_ingestion', 'manual_edit')",
        name="ck_change_sets_origin",
    ),
)

change_items = Table(
    "change_items", metadata,
    Column("id", String(40), primary_key=True),
    Column("user_id", String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("change_set_id", String(40), ForeignKey("change_sets.id", ondelete="CASCADE"), nullable=False),
    Column("operation", String(40), nullable=False),
    Column("target_document_id", String(40), ForeignKey("documents.id", ondelete="SET NULL")),
    Column("target_title", String(160), nullable=False),
    Column("before_title", String(160)),
    Column("reason", Text, nullable=False),
    Column("before_text", Text),
    Column("after_text", Text, nullable=False),
    Column("evidence", Text, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("accepted", Boolean),
    CheckConstraint(
        "operation IN ('CREATE_DOCUMENT', 'ADD_BLOCK', 'UPDATE_BLOCK', 'MOVE_BLOCK', "
        "'ADD_RELATION', 'MARK_DUPLICATE', 'REPORT_CONFLICT', 'UPDATE_DOCUMENT')",
        name="ck_change_items_operation",
    ),
    CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_change_items_confidence"),
)

user_memories = Table(
    "user_memories", metadata,
    Column("id", String(40), primary_key=True),
    Column("user_id", String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("kind", String(30), nullable=False),
    Column("content", Text, nullable=False),
    Column("scope", String(30), nullable=False),
    Column("scope_ref", String(160)),
    Column("status", String(20), nullable=False),
    Column("confidence", Float, nullable=False, server_default="1.0"),
    Column("origin", String(20), nullable=False),
    Column("use_count", Integer, nullable=False, server_default="0"),
    Column("last_used_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "kind IN ('style', 'topic_split', 'domain', 'naming', 'merge_preference')",
        name="ck_memories_kind",
    ),
    CheckConstraint("scope IN ('global', 'document', 'topic')", name="ck_memories_scope"),
    CheckConstraint("status IN ('active', 'candidate', 'suppressed')", name="ck_memories_status"),
    CheckConstraint(
        "origin IN ('user_explicit', 'ai_inferred', 'ai_observed')",
        name="ck_memories_origin",
    ),
    CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_memories_confidence"),
    CheckConstraint("use_count >= 0", name="ck_memories_use_count"),
)

chat_sessions = Table(
    "chat_sessions", metadata,
    Column("id", String(40), primary_key=True),
    Column("user_id", String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("title", String(80), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

chat_messages = Table(
    "chat_messages", metadata,
    Column("id", String(40), primary_key=True),
    Column("user_id", String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("session_id", String(40), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
    Column("role", String(20), nullable=False),
    Column("status", String(20), nullable=False),
    Column("content", Text, nullable=False),
    Column("include_public", Boolean, nullable=False, server_default="1"),
    Column("model", String(160)),
    Column("grounding", String(30)),
    Column("citations", JSON().with_variant(JSONB, "postgresql"), nullable=False),
    Column("error_code", String(80)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
    CheckConstraint("role IN ('user', 'assistant')", name="ck_chat_messages_role"),
    CheckConstraint(
        "status IN ('generating', 'completed', 'failed', 'cancelled')",
        name="ck_chat_messages_status",
    ),
    CheckConstraint(
        "grounding IS NULL OR grounding IN ('knowledge', 'knowledge_plus_general', 'general', 'insufficient')",
        name="ck_chat_messages_grounding",
    ),
)

knowledge_events = Table(
    "knowledge_events", metadata,
    Column("id", String(40), primary_key=True),
    Column("user_id", String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("change_set_id", String(40), ForeignKey("change_sets.id", ondelete="RESTRICT"), nullable=False),
    Column("title", String(160), nullable=False),
    Column("summary", Text, nullable=False),
    Column("affected_documents", JSON().with_variant(JSONB, "postgresql"), nullable=False),
    Column("accepted_count", Integer, nullable=False),
    Column("rejected_count", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("accepted_count >= 0", name="ck_events_accepted_count"),
    CheckConstraint("rejected_count >= 0", name="ck_events_rejected_count"),
)

Index("idx_sessions_user", sessions.c.user_id, sessions.c.expires_at.desc())
Index("idx_email_codes_email_created", email_verification_codes.c.email, email_verification_codes.c.created_at.desc())
Index("idx_sources_user", sources.c.user_id, sources.c.created_at.desc())
Index("idx_sources_user_status", sources.c.user_id, sources.c.processing_status, sources.c.created_at.desc())
Index("idx_sources_user_stage", sources.c.user_id, sources.c.processing_stage, sources.c.created_at.desc())
Index("idx_knowledge_units_source", knowledge_units.c.source_id)
Index("idx_knowledge_units_source_input", knowledge_units.c.source_id, knowledge_units.c.input_index)
Index("idx_knowledge_units_user", knowledge_units.c.user_id, knowledge_units.c.created_at.desc())
Index("idx_documents_user_updated", documents.c.user_id, documents.c.updated_at.desc())
Index("idx_documents_updated_at", documents.c.updated_at.desc())
Index("idx_documents_visibility_updated", documents.c.visibility, documents.c.updated_at.desc())
Index("uq_users_username", users.c.username, unique=True)
Index("idx_document_chunks_user", document_chunks.c.user_id, document_chunks.c.document_id)
Index("idx_document_chunks_document_version", document_chunks.c.document_id, document_chunks.c.document_version, document_chunks.c.ordinal)
Index("idx_document_chunks_user_status", document_chunks.c.user_id, document_chunks.c.embedding_status)
Index("idx_document_versions_document", document_versions.c.document_id, document_versions.c.version.desc())
Index("idx_change_sets_source", change_sets.c.source_id)
Index("idx_change_sets_status_created", change_sets.c.status, change_sets.c.created_at.desc())
Index("idx_change_items_change_set", change_items.c.change_set_id)
Index("idx_change_items_target_document", change_items.c.target_document_id)
Index("idx_knowledge_events_created_at", knowledge_events.c.created_at.desc())
Index("idx_knowledge_events_user_created", knowledge_events.c.user_id, knowledge_events.c.created_at.desc())
Index("idx_memories_user_active", user_memories.c.user_id, user_memories.c.status, user_memories.c.kind)
Index("idx_memories_user_created", user_memories.c.user_id, user_memories.c.created_at)
Index("idx_chat_sessions_user_updated", chat_sessions.c.user_id, chat_sessions.c.updated_at)
Index("idx_chat_messages_session_created", chat_messages.c.session_id, chat_messages.c.created_at)


class Store:
    """SQLAlchemy repository. Production uses PostgreSQL; tests use temporary SQLite."""

    def __init__(self, database_url: str | URL, *, create_schema: bool = True):
        self.engine = create_engine(database_url, pool_pre_ping=True)
        if create_schema:
            metadata.create_all(self.engine)

    def close(self) -> None:
        self.engine.dispose()

    def create_user(self, email: str, display_name: str) -> dict:
        created_at = now_utc()
        user_id = new_id("usr")
        try:
            with self.engine.begin() as db:
                db.execute(insert(users).values(
                    id=user_id, email=email, display_name=display_name,
                    role="user", username=None, password_hash=None,
                    status="active",
                    created_at=created_at, updated_at=created_at,
                ))
                legacy = db.execute(select(users.c.id).where(
                    users.c.id == LEGACY_USER_ID,
                    users.c.status == "disabled",
                )).first()
                if legacy:
                    for table in (sources, knowledge_units, documents, document_chunks, document_versions, change_sets, change_items, knowledge_events):
                        db.execute(update(table).where(table.c.user_id == LEGACY_USER_ID).values(user_id=user_id))
                    db.execute(delete(users).where(users.c.id == LEGACY_USER_ID))
        except IntegrityError:
            existing = self.get_user_by_email(email)
            if existing:
                return existing
            raise
        user = self.get_user(user_id)
        assert user is not None
        return user

    def get_user(self, user_id: str) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(select(users).where(users.c.id == user_id)).mappings().first()
            return dict(row) if row else None

    def get_user_by_email(self, email: str) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(select(users).where(users.c.email == email)).mappings().first()
            return dict(row) if row else None

    def get_user_by_username(self, username: str) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(select(users).where(users.c.username == username)).mappings().first()
            return dict(row) if row else None

    def ensure_admin(
        self, *, username: str, email: str, password_hash: str,
        password_matches: bool = False,
    ) -> bool:
        """Create or synchronize the configured administrator at application startup.

        Returns True when the stored password hash changed, allowing callers to
        revoke existing administrator sessions.
        """
        now = now_utc()
        with self.engine.begin() as db:
            current = db.execute(select(users).where(users.c.username == username).with_for_update()).mappings().first()
            if not current:
                db.execute(insert(users).values(
                    id=new_id("usr"), email=email, username=username,
                    display_name="Administrator", password_hash=password_hash,
                    role="admin", status="active", created_at=now, updated_at=now,
                ))
                return True
            changed = not password_matches
            values = {
                "email": email, "display_name": "Administrator", "role": "admin",
                "status": "active", "updated_at": now,
            }
            if changed:
                values["password_hash"] = password_hash
            db.execute(update(users).where(users.c.id == current["id"]).values(**values))
            if changed:
                db.execute(update(sessions).where(
                    sessions.c.user_id == current["id"], sessions.c.revoked_at.is_(None),
                ).values(revoked_at=now))
            return changed

    def list_users(self) -> list[dict]:
        with self.engine.connect() as db:
            query = select(
                users.c.id, users.c.email, users.c.username, users.c.display_name,
                users.c.role, users.c.status, users.c.created_at, users.c.updated_at,
                func.count(documents.c.id).label("document_count"),
                func.coalesce(func.sum(case((documents.c.visibility == "public", 1), else_=0)), 0).label("public_document_count"),
            ).select_from(users.outerjoin(documents, documents.c.user_id == users.c.id)).group_by(
                users.c.id,
            ).order_by(users.c.created_at.desc())
            rows = db.execute(query).mappings()
            return [dict(row) for row in rows]

    def list_knowledge_ownership(self) -> list[dict]:
        with self.engine.connect() as db:
            rows = db.execute(select(
                documents.c.id, documents.c.user_id, documents.c.title,
                documents.c.version, documents.c.visibility,
                documents.c.created_at, documents.c.updated_at,
                users.c.email.label("owner_email"),
                users.c.display_name.label("owner_display_name"),
            ).join(users, users.c.id == documents.c.user_id).order_by(
                documents.c.updated_at.desc(), documents.c.id,
            )).mappings()
            return [dict(row) for row in rows]

    def get_document_for_admin(self, document_id: str) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(select(documents).where(
                documents.c.id == document_id,
            )).mappings().first()
            return dict(row) if row else None

    def create_session(self, user_id: str, token_hash: str, expires_at: datetime) -> None:
        with self.engine.begin() as db:
            db.execute(insert(sessions).values(
                id=new_id("ses"), user_id=user_id, token_hash=token_hash,
                expires_at=expires_at, created_at=now_utc(), revoked_at=None,
            ))

    def get_session_user(self, token_hash: str, at: datetime) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(
                select(users).join(sessions, sessions.c.user_id == users.c.id).where(
                    sessions.c.token_hash == token_hash,
                    sessions.c.revoked_at.is_(None),
                    sessions.c.expires_at > at,
                    users.c.status == "active",
                )
            ).mappings().first()
            return dict(row) if row else None

    def revoke_session(self, token_hash: str, at: datetime) -> None:
        with self.engine.begin() as db:
            db.execute(update(sessions).where(
                sessions.c.token_hash == token_hash,
                sessions.c.revoked_at.is_(None),
            ).values(revoked_at=at))

    def verification_code_is_cooling_down(self, email: str, at: datetime) -> bool:
        with self.engine.connect() as db:
            row = db.execute(select(email_verification_codes.c.id).where(
                email_verification_codes.c.email == email,
                email_verification_codes.c.consumed_at.is_(None),
                email_verification_codes.c.resend_after > at,
            ).order_by(email_verification_codes.c.created_at.desc()).limit(1)).scalar_one_or_none()
            return row is not None

    def save_verification_code(self, email: str, code_hash: str, expires_at: datetime, resend_after: datetime) -> None:
        with self.engine.begin() as db:
            db.execute(insert(email_verification_codes).values(
                id=new_id("emc"), email=email, code_hash=code_hash, attempts=0,
                expires_at=expires_at, resend_after=resend_after,
                created_at=now_utc(), consumed_at=None,
            ))

    def consume_verification_code(self, email: str, code_hash: str, at: datetime) -> bool:
        with self.engine.begin() as db:
            row = db.execute(select(email_verification_codes).where(
                email_verification_codes.c.email == email,
                email_verification_codes.c.consumed_at.is_(None),
                email_verification_codes.c.expires_at > at,
                email_verification_codes.c.attempts < 5,
            ).order_by(email_verification_codes.c.created_at.desc()).limit(1).with_for_update()).mappings().first()
            if not row:
                return False
            if not hmac.compare_digest(row["code_hash"], code_hash):
                db.execute(update(email_verification_codes).where(
                    email_verification_codes.c.id == row["id"]
                ).values(attempts=row["attempts"] + 1))
                return False
            updated = db.execute(update(email_verification_codes).where(
                email_verification_codes.c.id == row["id"],
                email_verification_codes.c.consumed_at.is_(None),
            ).values(consumed_at=at))
            return updated.rowcount == 1

    def list_documents(self, user_id: str) -> list[dict]:
        with self.engine.connect() as db:
            rows = db.execute(select(documents).where(
                documents.c.user_id == user_id
            ).order_by(documents.c.updated_at.desc())).mappings()
            return [dict(row) for row in rows]

    def list_public_documents(self) -> list[dict]:
        with self.engine.connect() as db:
            rows = db.execute(select(documents).where(
                documents.c.visibility == "public",
            ).order_by(documents.c.updated_at.desc())).mappings()
            return [dict(row) for row in rows]

    def create_public_document(
        self, user_id: str, *, title: str, markdown: str, document_id: str | None = None,
    ) -> dict:
        now = now_utc()
        document_id = document_id or new_id("pub")
        with self.engine.begin() as db:
            db.execute(insert(documents).values(
                id=document_id, user_id=user_id, title=title.strip(), markdown=markdown.strip(),
                visibility="public", version=1, created_at=now, updated_at=now,
            ))
            db.execute(insert(document_versions).values(
                id=new_id("ver"), user_id=user_id, document_id=document_id, version=1,
                title=title.strip(), markdown=markdown.strip(), reason="创建大众知识库文档",
                created_at=now,
            ))
        try:
            self.stage_document_chunks(user_id, document_id)
        except Exception:
            logger.exception("public document chunk staging failed document_id=%s", document_id)
        return self.get_document(user_id, document_id) or {}

    def set_document_visibility(self, user_id: str, document_id: str, visibility: str) -> dict | None:
        with self.engine.begin() as db:
            result = db.execute(update(documents).where(
                documents.c.id == document_id,
                documents.c.user_id == user_id,
            ).values(visibility=visibility, updated_at=now_utc()))
            if result.rowcount != 1:
                return None
        return self.get_document(user_id, document_id)

    def get_document(self, user_id: str, document_id: str) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(select(documents).where(
                documents.c.id == document_id,
                (documents.c.user_id == user_id) | (documents.c.visibility == "public"),
            )).mappings().first()
            return dict(row) if row else None

    def list_document_chunks(
        self, user_id: str, *, document_id: str | None = None,
        current_only: bool = True,
    ) -> list[dict]:
        query = select(document_chunks).where(document_chunks.c.user_id == user_id)
        if document_id:
            query = query.where(document_chunks.c.document_id == document_id)
        if current_only:
            query = query.join(
                documents,
                (documents.c.id == document_chunks.c.document_id)
                & (documents.c.user_id == document_chunks.c.user_id),
            ).where(document_chunks.c.document_version == documents.c.version)
        query = query.order_by(document_chunks.c.document_id, document_chunks.c.ordinal)
        with self.engine.connect() as db:
            return [dict(row) for row in db.execute(query).mappings()]

    def list_search_chunks(
        self, user_id: str, document_id: str | None = None, *, include_public: bool = False,
    ) -> list[dict]:
        query = select(
            document_chunks,
            documents.c.title.label("document_title"),
            documents.c.version.label("current_version"),
            documents.c.visibility,
        ).join(documents, documents.c.id == document_chunks.c.document_id).where(
            ((document_chunks.c.user_id == user_id) | (documents.c.visibility == "public"))
            if include_public else document_chunks.c.user_id == user_id,
            document_chunks.c.document_version == documents.c.version,
        )
        if document_id:
            query = query.where(document_chunks.c.document_id == document_id)
        query = query.order_by(document_chunks.c.document_id, document_chunks.c.ordinal)
        with self.engine.connect() as db:
            return [dict(row) for row in db.execute(query).mappings()]

    def replace_document_chunks(
        self, user_id: str, document_id: str, document_version: int,
        chunks: list[dict], *, embedding_model: str | None = None,
    ) -> list[dict]:
        now = now_utc()
        with self.engine.begin() as db:
            owned = db.execute(select(documents.c.id).where(
                documents.c.id == document_id,
                documents.c.user_id == user_id,
                documents.c.version == document_version,
            )).first()
            if not owned:
                return []
            db.execute(delete(document_chunks).where(
                document_chunks.c.user_id == user_id,
                document_chunks.c.document_id == document_id,
            ))
            values = []
            for ordinal, chunk in enumerate(chunks):
                values.append({
                    "id": chunk.get("id") or new_id("chk"),
                    "user_id": user_id,
                    "document_id": document_id,
                    "document_version": document_version,
                    "ordinal": ordinal,
                    "content": chunk["content"],
                    "embedding": chunk.get("embedding"),
                    "embedding_model": embedding_model if chunk.get("embedding") is not None else None,
                    "embedding_status": chunk.get("embedding_status", "ready" if chunk.get("embedding") is not None else "failed"),
                    "created_at": now,
                    "updated_at": now,
                })
            if values:
                db.execute(insert(document_chunks), values)
        return self.list_search_chunks(user_id, document_id)

    def stage_document_chunks(self, user_id: str, document_id: str) -> list[dict]:
        """Persist current-version text chunks before best-effort embedding runs."""
        from .retrieval import chunk_markdown

        document = self.get_document(user_id, document_id)
        if not document:
            return []
        payload = [
            {"content": content, "embedding_status": "pending"}
            for content in chunk_markdown(document["title"], document["markdown"])
        ]
        return self.replace_document_chunks(
            user_id, document_id, document["version"], payload,
        )

    def list_document_versions(self, user_id: str, document_id: str) -> list[dict] | None:
        with self.engine.connect() as db:
            document = db.execute(select(documents.c.id).where(
                documents.c.id == document_id,
                (documents.c.user_id == user_id) | (documents.c.visibility == "public"),
            )).first()
            if not document:
                return None
            rows = db.execute(select(document_versions).join(
                documents, documents.c.id == document_versions.c.document_id,
            ).where(
                document_versions.c.document_id == document_id,
                (document_versions.c.user_id == user_id) | (documents.c.visibility == "public"),
            ).order_by(document_versions.c.version.desc())).mappings()
            return [dict(row) for row in rows]

    def export_documents_snapshot(
        self, user_id: str, *, document_id: str | None = None,
        version: int | None = None,
    ) -> list[dict] | None:
        """Return a consistent current or historical document snapshot for human exports."""
        with self.engine.connect() as raw_db:
            db = raw_db.execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True,
            ) if self.engine.dialect.name == "postgresql" else raw_db
            with db.begin():
                if document_id is None:
                    rows = db.execute(select(documents).where(
                        documents.c.user_id == user_id,
                    ).order_by(documents.c.title, documents.c.id)).mappings()
                    return [dict(row) for row in rows]

                current = db.execute(select(documents).where(
                    documents.c.id == document_id,
                    documents.c.user_id == user_id,
                )).mappings().first()
                if not current:
                    return None
                if version is None or version == current["version"]:
                    return [dict(current)]
                historical = db.execute(select(document_versions).where(
                    document_versions.c.document_id == document_id,
                    document_versions.c.user_id == user_id,
                    document_versions.c.version == version,
                )).mappings().first()
                if not historical:
                    return None
                return [{
                    "id": current["id"], "user_id": user_id,
                    "title": historical["title"], "markdown": historical["markdown"],
                    "version": historical["version"], "created_at": historical["created_at"],
                    "updated_at": historical["created_at"],
                }]

    def export_knowledge_snapshot(
        self, user_id: str, *, document_id: str | None = None,
    ) -> dict[str, list[dict]] | None:
        """Return a user-scoped, consistent knowledge graph snapshot for machine export."""
        with self.engine.connect() as raw_db:
            db = raw_db.execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True,
            ) if self.engine.dialect.name == "postgresql" else raw_db
            with db.begin():
                document_query = select(documents).where(documents.c.user_id == user_id)
                if document_id is not None:
                    document_query = document_query.where(documents.c.id == document_id)
                document_rows = [dict(row) for row in db.execute(
                    document_query.order_by(documents.c.title, documents.c.id)
                ).mappings()]
                if document_id is not None and not document_rows:
                    return None

                if document_id is None:
                    version_rows = [dict(row) for row in db.execute(select(document_versions).where(
                        document_versions.c.user_id == user_id,
                    ).order_by(document_versions.c.document_id, document_versions.c.version)).mappings()]
                    source_rows = [dict(row) for row in db.execute(select(sources).where(
                        sources.c.user_id == user_id,
                    ).order_by(sources.c.created_at, sources.c.id)).mappings()]
                    unit_rows = [dict(row) for row in db.execute(select(knowledge_units).where(
                        knowledge_units.c.user_id == user_id,
                    ).order_by(knowledge_units.c.created_at, knowledge_units.c.id)).mappings()]
                    set_rows = [dict(row) for row in db.execute(select(change_sets).where(
                        change_sets.c.user_id == user_id,
                    ).order_by(change_sets.c.created_at, change_sets.c.id)).mappings()]
                    item_rows = [dict(row) for row in db.execute(select(change_items).where(
                        change_items.c.user_id == user_id,
                    ).order_by(change_items.c.change_set_id, change_items.c.id)).mappings()]
                    event_rows = [dict(row) for row in db.execute(select(knowledge_events).where(
                        knowledge_events.c.user_id == user_id,
                    ).order_by(knowledge_events.c.created_at, knowledge_events.c.id)).mappings()]
                else:
                    version_rows = [dict(row) for row in db.execute(select(document_versions).where(
                        document_versions.c.user_id == user_id,
                        document_versions.c.document_id == document_id,
                    ).order_by(document_versions.c.version)).mappings()]
                    item_rows = [dict(row) for row in db.execute(select(change_items).where(
                        change_items.c.user_id == user_id,
                        change_items.c.target_document_id == document_id,
                    ).order_by(change_items.c.change_set_id, change_items.c.id)).mappings()]
                    set_ids = {row["change_set_id"] for row in item_rows}
                    set_rows = [] if not set_ids else [dict(row) for row in db.execute(select(change_sets).where(
                        change_sets.c.user_id == user_id,
                        change_sets.c.id.in_(set_ids),
                    ).order_by(change_sets.c.created_at, change_sets.c.id)).mappings()]
                    source_ids = {row["source_id"] for row in set_rows if row["source_id"]}
                    source_rows = [] if not source_ids else [dict(row) for row in db.execute(select(sources).where(
                        sources.c.user_id == user_id,
                        sources.c.id.in_(source_ids),
                    ).order_by(sources.c.created_at, sources.c.id)).mappings()]
                    unit_rows = [] if not source_ids else [dict(row) for row in db.execute(select(knowledge_units).where(
                        knowledge_units.c.user_id == user_id,
                        knowledge_units.c.source_id.in_(source_ids),
                    ).order_by(knowledge_units.c.created_at, knowledge_units.c.id)).mappings()]
                    event_rows = [] if not set_ids else [dict(row) for row in db.execute(select(knowledge_events).where(
                        knowledge_events.c.user_id == user_id,
                        knowledge_events.c.change_set_id.in_(set_ids),
                    ).order_by(knowledge_events.c.created_at, knowledge_events.c.id)).mappings()]

                return {
                    "documents": document_rows,
                    "document_versions": version_rows,
                    "sources": source_rows,
                    "knowledge_units": unit_rows,
                    "change_sets": set_rows,
                    "change_items": item_rows,
                    "knowledge_events": event_rows,
                }

    def create_source(self, user_id: str, kind: str, content: str, title: str | None) -> dict:
        source_id = new_id("src")
        with self.engine.begin() as db:
            db.execute(insert(sources).values(
                id=source_id, user_id=user_id, kind=kind, title=title, content=content,
                processing_status="received", ai_provider=None, ai_model=None,
                prompt_version=None, error_code=None, error_message=None,
                processing_stage="queued", processing_started_at=None,
                total_inputs=0, processed_inputs=0, ocr_model=None, ocr_prompt_version=None,
                covered_inputs=0, extraction_attempts=0,
                pending_supersedes_change_set_id=None, pending_analysis_instruction=None,
                processed_at=None, created_at=now_utc(),
            ))
        source = self.get_source(user_id, source_id)
        assert source is not None
        return source

    def create_image_source(
        self, user_id: str, *, title: str | None, total_inputs: int,
        ocr_model: str, ocr_prompt_version: str,
    ) -> dict:
        source_id = new_id("src")
        with self.engine.begin() as db:
            db.execute(insert(sources).values(
                id=source_id, user_id=user_id, kind="image", title=title,
                content="", processing_status="received",
                ai_provider=None, ai_model=None, prompt_version=None,
                error_code=None, error_message=None, processing_stage="queued",
                processing_started_at=None, total_inputs=total_inputs, processed_inputs=0,
                covered_inputs=0, extraction_attempts=0,
                pending_supersedes_change_set_id=None, pending_analysis_instruction=None,
                ocr_model=ocr_model, ocr_prompt_version=ocr_prompt_version,
                processed_at=None, created_at=now_utc(),
            ))
        source = self.get_source(user_id, source_id)
        assert source is not None
        return source

    def get_source(self, user_id: str, source_id: str) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(select(sources).where(
                sources.c.id == source_id,
                sources.c.user_id == user_id,
            )).mappings().first()
            return dict(row) if row else None

    def claim_source_for_processing(
        self, user_id: str, source_id: str, *, provider: str, model: str, prompt_version: str,
    ) -> dict | None:
        with self.engine.begin() as db:
            result = db.execute(update(sources).where(
                sources.c.id == source_id,
                sources.c.user_id == user_id,
                sources.c.processing_status.in_(("received", "failed")),
            ).values(
                processing_status="processing", ai_provider=provider, ai_model=model,
                prompt_version=prompt_version, error_code=None, error_message=None,
                processing_stage="extracting", processing_started_at=now_utc(), processed_at=None,
                covered_inputs=0, extraction_attempts=0,
            ))
            if result.rowcount != 1:
                return None
        return self.get_source(user_id, source_id)

    def start_image_ocr(self, user_id: str, source_id: str) -> dict | None:
        with self.engine.begin() as db:
            result = db.execute(update(sources).where(
                sources.c.id == source_id,
                sources.c.user_id == user_id,
                sources.c.kind == "image",
                sources.c.processing_status == "received",
            ).values(
                processing_status="processing", processing_stage="ocr",
                processing_started_at=now_utc(), error_code=None, error_message=None,
                processed_inputs=0, covered_inputs=0, extraction_attempts=0,
                processed_at=None,
            ))
            if result.rowcount != 1:
                return None
        return self.get_source(user_id, source_id)

    def update_source_stage(self, user_id: str, source_id: str, stage: str) -> None:
        with self.engine.begin() as db:
            db.execute(update(sources).where(
                sources.c.id == source_id,
                sources.c.user_id == user_id,
                sources.c.processing_status == "processing",
            ).values(processing_stage=stage))

    def update_extraction_progress(
        self, user_id: str, source_id: str, *, covered_inputs: int,
        extraction_attempts: int, stage: str,
    ) -> None:
        with self.engine.begin() as db:
            db.execute(update(sources).where(
                sources.c.id == source_id,
                sources.c.user_id == user_id,
                sources.c.processing_status == "processing",
            ).values(
                covered_inputs=covered_inputs,
                extraction_attempts=extraction_attempts,
                processing_stage=stage,
            ))

    def increment_processed_inputs(self, user_id: str, source_id: str) -> None:
        with self.engine.begin() as db:
            db.execute(update(sources).where(
                sources.c.id == source_id,
                sources.c.user_id == user_id,
                sources.c.processing_status == "processing",
                sources.c.processed_inputs < sources.c.total_inputs,
            ).values(processed_inputs=sources.c.processed_inputs + 1))

    def save_ocr_content(self, user_id: str, source_id: str, content: str) -> None:
        with self.engine.begin() as db:
            result = db.execute(update(sources).where(
                sources.c.id == source_id,
                sources.c.user_id == user_id,
                sources.c.kind == "image",
                sources.c.processing_status == "processing",
            ).values(
                content=content, processing_stage="extracting",
                processed_inputs=sources.c.total_inputs,
            ))
            if result.rowcount != 1:
                raise ValueError("Image source is not processing or does not belong to user")

    def get_source_processing(self, user_id: str, source_id: str) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(select(sources).where(
                sources.c.id == source_id,
                sources.c.user_id == user_id,
            )).mappings().first()
            if not row:
                return None
            result = dict(row)
            result["change_set_id"] = db.execute(select(change_sets.c.id).where(
                change_sets.c.source_id == source_id,
                change_sets.c.user_id == user_id,
                change_sets.c.status != "superseded",
            ).order_by(change_sets.c.created_at.desc()).limit(1)).scalar_one_or_none()
            counts = dict(db.execute(select(
                knowledge_units.c.input_index, func.count(knowledge_units.c.id),
            ).where(
                knowledge_units.c.source_id == source_id,
                knowledge_units.c.user_id == user_id,
            ).group_by(knowledge_units.c.input_index)).all())
            indexes = (
                range(1, result["total_inputs"] + 1)
                if result["kind"] == "image" else (0,)
            )
            result["input_coverage"] = [
                {"input_index": index, "knowledge_unit_count": counts.get(index, 0)}
                for index in indexes
            ]
            return result

    def fail_interrupted_image_sources(self) -> int:
        with self.engine.begin() as db:
            result = db.execute(update(sources).where(
                sources.c.kind == "image",
                sources.c.processing_status.in_(("received", "processing")),
            ).values(
                processing_status="failed", processing_stage="failed",
                error_code=case(
                    (sources.c.processing_stage.in_(("queued", "ocr")), "WORKER_INTERRUPTED"),
                    else_="AI_WORKER_INTERRUPTED",
                ),
                error_message=case(
                    (
                        sources.c.processing_stage.in_(("queued", "ocr")),
                        "图片识别因服务重启中断，请重新上传",
                    ),
                    else_="知识整合因服务重启中断，可直接重试",
                ),
                processed_at=now_utc(),
            ))
            return result.rowcount

    def queue_source_retry(self, user_id: str, source_id: str) -> dict | None:
        with self.engine.begin() as db:
            result = db.execute(update(sources).where(
                sources.c.id == source_id,
                sources.c.user_id == user_id,
                sources.c.processing_status == "failed",
            ).values(
                processing_status="received", processing_stage="queued",
                processing_started_at=None, error_code=None, error_message=None,
                covered_inputs=0, extraction_attempts=0, processed_at=None,
            ))
            if result.rowcount != 1:
                return None
        return self.get_source_processing(user_id, source_id)

    def queue_source_reprocess(
        self, user_id: str, source_id: str, replaces_change_set_id: str,
        instruction: str | None,
    ) -> dict | None:
        with self.engine.begin() as db:
            draft = db.execute(select(change_sets.c.id).where(
                change_sets.c.id == replaces_change_set_id,
                change_sets.c.user_id == user_id,
                change_sets.c.source_id == source_id,
                change_sets.c.status == "proposed",
            )).first()
            if not draft:
                return None
            result = db.execute(update(sources).where(
                sources.c.id == source_id,
                sources.c.user_id == user_id,
                sources.c.processing_status.in_(("proposed", "failed")),
            ).values(
                processing_status="received", processing_stage="queued",
                processing_started_at=None, error_code=None, error_message=None,
                covered_inputs=0, extraction_attempts=0, processed_at=None,
                pending_supersedes_change_set_id=replaces_change_set_id,
                pending_analysis_instruction=instruction,
            ))
            if result.rowcount != 1:
                return None
        return self.get_source_processing(user_id, source_id)

    def save_extraction(self, user_id: str, source_id: str, extraction: ExtractionResult) -> None:
        created_at = now_utc()
        with self.engine.begin() as db:
            source = db.execute(select(sources.c.id).where(
                sources.c.id == source_id,
                sources.c.user_id == user_id,
                sources.c.processing_status == "processing",
            ).with_for_update()).first()
            if not source:
                raise ValueError("Source is not processing or does not belong to user")
            db.execute(delete(knowledge_units).where(
                knowledge_units.c.source_id == source_id,
                knowledge_units.c.user_id == user_id,
            ))
            for unit in extraction.units:
                db.execute(insert(knowledge_units).values(
                    id=new_id("unit"), user_id=user_id, source_id=source_id,
                    input_index=unit.input_index, type=unit.type,
                    subject=unit.subject, content=unit.content,
                    source_span=unit.source_span, confidence=unit.confidence,
                    created_at=created_at,
                ))

    def mark_source_failed(self, user_id: str, source_id: str, error_code: str, error_message: str) -> None:
        with self.engine.begin() as db:
            db.execute(update(sources).where(
                sources.c.id == source_id,
                sources.c.user_id == user_id,
            ).values(
                processing_status="failed", processing_stage="failed", error_code=error_code,
                error_message=error_message[:2000], processed_at=now_utc(),
            ))

    def create_change_set_for_source(
        self, user_id: str, source_id: str, proposals: list[MergeProposal],
        *, extraction: ExtractionResult | None = None,
        supersedes_change_set_id: str | None = None,
        analysis_instruction: str | None = None,
        covered_inputs: int = 0, extraction_attempts: int = 0,
    ) -> dict:
        if not proposals:
            raise ValueError("At least one proposal is required")
        change_set_id, created_at = new_id("chg"), now_utc()
        with self.engine.begin() as db:
            source = db.execute(select(sources.c.id).where(
                sources.c.id == source_id,
                sources.c.user_id == user_id,
                sources.c.processing_status == "processing",
            ).with_for_update()).first()
            if not source:
                raise ValueError("Source is not processing or does not belong to user")
            if supersedes_change_set_id:
                previous = db.execute(select(change_sets.c.id).where(
                    change_sets.c.id == supersedes_change_set_id,
                    change_sets.c.source_id == source_id,
                    change_sets.c.user_id == user_id,
                    change_sets.c.status == "proposed",
                ).with_for_update()).first()
                if not previous:
                    raise ValueError("Change set to supersede is not an active draft")
            else:
                existing = db.execute(select(change_sets.c.id).where(
                    change_sets.c.source_id == source_id,
                    change_sets.c.user_id == user_id,
                )).first()
                if existing:
                    raise ValueError("Source already has a change set")
            for proposal in proposals:
                if proposal.target_document_id:
                    target = db.execute(select(documents.c.id).where(
                        documents.c.id == proposal.target_document_id,
                        documents.c.user_id == user_id,
                    )).first()
                    if not target:
                        raise ValueError("Proposal target does not belong to user")
            db.execute(insert(change_sets).values(
                id=change_set_id, user_id=user_id, source_id=source_id,
                origin="ai_ingestion",
                status="proposed", summary=f"AI generated {len(proposals)} changes for review",
                supersedes_change_set_id=supersedes_change_set_id,
                analysis_instruction=analysis_instruction,
                created_at=created_at,
            ))
            for proposal in proposals:
                db.execute(insert(change_items).values(
                    id=new_id("item"), user_id=user_id, change_set_id=change_set_id,
                    operation=proposal.operation, target_document_id=proposal.target_document_id,
                    target_title=proposal.target_title, before_title=proposal.target_title if proposal.before else None,
                    reason=proposal.reason,
                    before_text=proposal.before, after_text=proposal.after,
                    evidence=proposal.evidence, confidence=proposal.confidence,
                ))
            if extraction is not None:
                db.execute(delete(knowledge_units).where(
                    knowledge_units.c.source_id == source_id,
                    knowledge_units.c.user_id == user_id,
                ))
                for unit in extraction.units:
                    db.execute(insert(knowledge_units).values(
                        id=new_id("unit"), user_id=user_id, source_id=source_id,
                        input_index=unit.input_index, type=unit.type,
                        subject=unit.subject, content=unit.content,
                        source_span=unit.source_span, confidence=unit.confidence,
                        created_at=created_at,
                    ))
            if supersedes_change_set_id:
                db.execute(update(change_sets).where(
                    change_sets.c.id == supersedes_change_set_id,
                    change_sets.c.user_id == user_id,
                ).values(status="superseded"))
            db.execute(update(sources).where(
                sources.c.id == source_id,
                sources.c.user_id == user_id,
            ).values(
                processing_status="proposed", processing_stage="complete",
                error_code=None, error_message=None,
                covered_inputs=covered_inputs,
                extraction_attempts=extraction_attempts,
                pending_supersedes_change_set_id=None,
                pending_analysis_instruction=None,
                processed_at=created_at,
            ))
        result = self.get_change_set(user_id, change_set_id)
        assert result is not None
        return result

    def create_change_set(self, user_id: str, kind: str, content: str, title: str | None, proposal: MergeProposal) -> dict:
        source = self.create_source(user_id, kind, content, title)
        claimed = self.claim_source_for_processing(
            user_id, source["id"], provider="local", model="compatibility",
            prompt_version="compatibility-v1",
        )
        assert claimed is not None
        return self.create_change_set_for_source(user_id, source["id"], [proposal])

    def get_change_set(self, user_id: str, change_set_id: str) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(select(change_sets).where(
                change_sets.c.id == change_set_id,
                change_sets.c.user_id == user_id,
            )).mappings().first()
            if not row:
                return None
            result = dict(row)
            if result["source_id"]:
                source = db.execute(select(sources.c.title, sources.c.content).where(
                    sources.c.id == result["source_id"],
                    sources.c.user_id == user_id,
                )).mappings().first()
                result["source"] = dict(source) if source else None
            else:
                result["source"] = None
            items = db.execute(select(change_items).where(
                change_items.c.change_set_id == change_set_id,
                change_items.c.user_id == user_id,
            )).mappings()
            result["items"] = [{
                "id": item["id"], "operation": item["operation"],
                "target_document_id": item["target_document_id"], "target_title": item["target_title"],
                "before_title": item["before_title"],
                "reason": item["reason"], "before": item["before_text"], "after": item["after_text"],
                "evidence": item["evidence"], "confidence": item["confidence"],
                "accepted": item["accepted"],
            } for item in items]
            return result

    def apply_change_set(self, user_id: str, change_set_id: str, accepted_ids: list[str] | None) -> dict | None:
        change_set = self.get_change_set(user_id, change_set_id)
        if not change_set or change_set["status"] != "proposed":
            return None
        allowed = set(accepted_ids) if accepted_ids is not None else {item["id"] for item in change_set["items"]}
        affected: list[str] = []
        affected_ids: set[str] = set()
        accepted = 0
        created_at = now_utc()

        with self.engine.begin() as db:
            locked = db.execute(select(change_sets.c.status).join(
                sources, sources.c.id == change_sets.c.source_id,
            ).where(
                change_sets.c.id == change_set_id,
                change_sets.c.user_id == user_id,
                sources.c.user_id == user_id,
            ).with_for_update()).first()
            if not locked or locked.status != "proposed":
                return None
            locked_items = db.execute(select(change_items).where(
                change_items.c.change_set_id == change_set_id,
                change_items.c.user_id == user_id,
            ).with_for_update()).mappings().all()
            for row in locked_items:
                item = {
                    "id": row["id"], "operation": row["operation"],
                    "target_document_id": row["target_document_id"],
                    "target_title": row["target_title"], "reason": row["reason"],
                    "after": row["after_text"],
                }
                is_accepted = item["id"] in allowed
                db.execute(update(change_items).where(
                    change_items.c.id == item["id"],
                    change_items.c.change_set_id == change_set_id,
                    change_items.c.user_id == user_id,
                ).values(accepted=is_accepted))
                if not is_accepted:
                    continue
                accepted += 1
                if item["operation"] == "CREATE_DOCUMENT":
                    document_id = new_id("doc")
                    markdown = item["after"]
                    db.execute(insert(documents).values(
                        id=document_id, user_id=user_id, title=item["target_title"], markdown=markdown,
                        version=1, created_at=created_at, updated_at=created_at,
                    ))
                    db.execute(insert(document_versions).values(
                        id=new_id("ver"), user_id=user_id, document_id=document_id, version=1,
                        title=item["target_title"], markdown=markdown,
                        reason=item["reason"], created_at=created_at,
                    ))
                    db.execute(update(change_items).where(
                        change_items.c.id == item["id"],
                        change_items.c.user_id == user_id,
                    ).values(target_document_id=document_id))
                    affected.append(item["target_title"])
                    affected_ids.add(document_id)
                elif item["operation"] == "ADD_BLOCK" and item["target_document_id"]:
                    current = db.execute(
                        select(documents).where(
                            documents.c.id == item["target_document_id"],
                            documents.c.user_id == user_id,
                        ).with_for_update()
                    ).mappings().first()
                    if current:
                        version = current["version"] + 1
                        markdown = current["markdown"].rstrip() + "\n\n" + item["after"].strip() + "\n"
                        db.execute(update(documents).where(
                            documents.c.id == current["id"], documents.c.user_id == user_id,
                        ).values(
                            markdown=markdown, version=version, updated_at=created_at,
                        ))
                        db.execute(insert(document_versions).values(
                            id=new_id("ver"), user_id=user_id, document_id=current["id"], version=version,
                            title=current["title"], markdown=markdown,
                            reason=item["reason"], created_at=created_at,
                        ))
                        affected.append(current["title"])
                        affected_ids.add(current["id"])

            total = len(locked_items)
            status = "applied" if accepted == total else "partially_applied"
            db.execute(update(change_sets).where(
                change_sets.c.id == change_set_id,
                change_sets.c.user_id == user_id,
            ).values(status=status))
            db.execute(insert(knowledge_events).values(
                id=new_id("evt"), user_id=user_id, change_set_id=change_set_id, title="知识库已成长",
                summary=f"接受 {accepted} 项变更，影响 {len(affected)} 个文档",
                affected_documents=affected, accepted_count=accepted,
                rejected_count=total - accepted, created_at=created_at,
            ))
        for document_id in affected_ids:
            try:
                self.stage_document_chunks(user_id, document_id)
            except Exception:
                logger.exception("text chunk staging failed document_id=%s", document_id)
        return self.get_change_set(user_id, change_set_id)

    def update_document(
        self, user_id: str, document_id: str, *, title: str, markdown: str,
        base_version: int, reason: str | None,
    ) -> dict | None:
        title = title.strip()
        markdown = markdown.strip()
        change_reason = (reason or "").strip() or "手工编辑文档"
        created_at = now_utc()
        with self.engine.begin() as db:
            current = db.execute(select(documents).where(
                documents.c.id == document_id,
                documents.c.user_id == user_id,
            ).with_for_update()).mappings().first()
            if not current:
                return None
            if current["version"] != base_version:
                raise DocumentVersionConflict(current["version"])
            if current["title"] == title and current["markdown"].strip() == markdown:
                return dict(current)

            version = current["version"] + 1
            change_set_id = new_id("chg")
            db.execute(update(documents).where(
                documents.c.id == document_id,
                documents.c.user_id == user_id,
            ).values(title=title, markdown=markdown, version=version, updated_at=created_at))
            db.execute(insert(document_versions).values(
                id=new_id("ver"), user_id=user_id, document_id=document_id,
                version=version, title=title, markdown=markdown,
                reason=change_reason, created_at=created_at,
            ))
            db.execute(insert(change_sets).values(
                id=change_set_id, user_id=user_id, source_id=None,
                origin="manual_edit", status="applied", summary=change_reason,
                created_at=created_at,
            ))
            db.execute(insert(change_items).values(
                id=new_id("item"), user_id=user_id, change_set_id=change_set_id,
                operation="UPDATE_DOCUMENT", target_document_id=document_id,
                target_title=title, before_title=current["title"], reason=change_reason,
                before_text=current["markdown"], after_text=markdown,
                evidence="由用户直接编辑", confidence=1.0, accepted=True,
            ))
            db.execute(insert(knowledge_events).values(
                id=new_id("evt"), user_id=user_id, change_set_id=change_set_id,
                title="文档已由你更新", summary=f"已保存《{title}》的第 {version} 版",
                affected_documents=[title], accepted_count=1, rejected_count=0,
                created_at=created_at,
            ))
        try:
            self.stage_document_chunks(user_id, document_id)
        except Exception:
            logger.exception("text chunk staging failed document_id=%s", document_id)
        return self.get_document(user_id, document_id)

    def list_events(self, user_id: str) -> list[dict]:
        with self.engine.connect() as db:
            rows = db.execute(select(knowledge_events, change_sets.c.origin).join(
                change_sets, change_sets.c.id == knowledge_events.c.change_set_id,
            ).where(
                knowledge_events.c.user_id == user_id
            ).order_by(knowledge_events.c.created_at.desc())).mappings()
            return [dict(row) for row in rows]

    def list_memories(
        self, user_id: str, *, status: str | None = None, scope: str | None = None,
    ) -> list[dict]:
        with self.engine.connect() as db:
            query = select(user_memories).where(user_memories.c.user_id == user_id)
            if status:
                query = query.where(user_memories.c.status == status)
            if scope:
                query = query.where(user_memories.c.scope == scope)
            rows = db.execute(query.order_by(user_memories.c.created_at.desc())).mappings()
            return [dict(row) for row in rows]

    def get_memory(self, user_id: str, memory_id: str) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(select(user_memories).where(
                user_memories.c.id == memory_id,
                user_memories.c.user_id == user_id,
            )).mappings().first()
            return dict(row) if row else None

    def create_memory(
        self, user_id: str, *, kind: str, content: str, scope: str, scope_ref: str | None,
        status: str, confidence: float, origin: str,
    ) -> dict:
        memory_id = new_id("mem")
        created_at = now_utc()
        with self.engine.begin() as db:
            db.execute(insert(user_memories).values(
                id=memory_id, user_id=user_id, kind=kind, content=content,
                scope=scope, scope_ref=scope_ref, status=status,
                confidence=confidence, origin=origin, use_count=0,
                last_used_at=None, created_at=created_at, updated_at=created_at,
            ))
        memory = self.get_memory(user_id, memory_id)
        assert memory is not None
        return memory

    def update_memory(
        self, user_id: str, memory_id: str, *, content: str | None = None,
        status: str | None = None,
    ) -> dict | None:
        updated_at = now_utc()
        updates = {"updated_at": updated_at}
        if content is not None:
            updates["content"] = content
        if status is not None:
            updates["status"] = status
        with self.engine.begin() as db:
            result = db.execute(update(user_memories).where(
                user_memories.c.id == memory_id,
                user_memories.c.user_id == user_id,
            ).values(**updates))
            if result.rowcount != 1:
                return None
        return self.get_memory(user_id, memory_id)

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        with self.engine.begin() as db:
            result = db.execute(delete(user_memories).where(
                user_memories.c.id == memory_id,
                user_memories.c.user_id == user_id,
            ))
            return result.rowcount == 1

    def increment_memory_usage(self, user_id: str, memory_ids: list[str]) -> None:
        if not memory_ids:
            return
        used_at = now_utc()
        with self.engine.begin() as db:
            db.execute(update(user_memories).where(
                user_memories.c.user_id == user_id,
                user_memories.c.id.in_(memory_ids),
            ).values(
                use_count=user_memories.c.use_count + 1,
                last_used_at=used_at,
            ))

    def create_chat_session(self, user_id: str, title: str = "新对话") -> dict:
        session_id = new_id("cht")
        created_at = now_utc()
        with self.engine.begin() as db:
            db.execute(insert(chat_sessions).values(
                id=session_id, user_id=user_id, title=title,
                created_at=created_at, updated_at=created_at,
            ))
        result = self.get_chat_session(user_id, session_id)
        assert result is not None
        return result

    def list_chat_sessions(self, user_id: str) -> list[dict]:
        with self.engine.connect() as db:
            rows = db.execute(select(chat_sessions).where(
                chat_sessions.c.user_id == user_id,
            ).order_by(chat_sessions.c.updated_at.desc()).limit(100)).mappings()
            return [dict(row) for row in rows]

    def get_chat_session(self, user_id: str, session_id: str) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(select(chat_sessions).where(
                chat_sessions.c.id == session_id,
                chat_sessions.c.user_id == user_id,
            )).mappings().first()
            return dict(row) if row else None

    def update_chat_session(self, user_id: str, session_id: str, title: str) -> dict | None:
        with self.engine.begin() as db:
            result = db.execute(update(chat_sessions).where(
                chat_sessions.c.id == session_id,
                chat_sessions.c.user_id == user_id,
            ).values(title=title, updated_at=now_utc()))
            if result.rowcount != 1:
                return None
        return self.get_chat_session(user_id, session_id)

    def delete_chat_session(self, user_id: str, session_id: str) -> str:
        with self.engine.begin() as db:
            owned = db.execute(select(chat_sessions.c.id).where(
                chat_sessions.c.id == session_id,
                chat_sessions.c.user_id == user_id,
            )).first()
            if not owned:
                return "not_found"
            busy = db.execute(select(chat_messages.c.id).where(
                chat_messages.c.session_id == session_id,
                chat_messages.c.user_id == user_id,
                chat_messages.c.status == "generating",
            ).limit(1)).first()
            if busy:
                return "busy"
            db.execute(delete(chat_sessions).where(chat_sessions.c.id == session_id))
            return "deleted"

    def list_chat_messages(self, user_id: str, session_id: str, limit: int = 200) -> list[dict] | None:
        with self.engine.connect() as db:
            owned = db.execute(select(chat_sessions.c.id).where(
                chat_sessions.c.id == session_id,
                chat_sessions.c.user_id == user_id,
            )).first()
            if not owned:
                return None
            rows = list(db.execute(select(chat_messages).where(
                chat_messages.c.session_id == session_id,
                chat_messages.c.user_id == user_id,
            ).order_by(chat_messages.c.created_at.desc(), chat_messages.c.id.desc()).limit(limit)).mappings())
            return [dict(row) for row in reversed(rows)]

    def get_chat_message(self, user_id: str, message_id: str) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(select(chat_messages).where(
                chat_messages.c.id == message_id,
                chat_messages.c.user_id == user_id,
            )).mappings().first()
            return dict(row) if row else None

    def create_chat_turn(
        self, user_id: str, session_id: str, content: str, model: str,
        include_public: bool = True,
    ) -> tuple[dict, dict] | None:
        user_message_id = new_id("msg")
        assistant_message_id = new_id("msg")
        user_created_at = now_utc()
        assistant_created_at = user_created_at + timedelta(microseconds=1)
        with self.engine.begin() as db:
            session = db.execute(select(chat_sessions).where(
                chat_sessions.c.id == session_id,
                chat_sessions.c.user_id == user_id,
            ).with_for_update()).mappings().first()
            if not session:
                return None
            if db.execute(select(chat_messages.c.id).where(
                chat_messages.c.session_id == session_id,
                chat_messages.c.user_id == user_id,
                chat_messages.c.status == "generating",
            ).limit(1)).first():
                raise ChatSessionBusy()
            has_user_message = db.execute(select(chat_messages.c.id).where(
                chat_messages.c.session_id == session_id,
                chat_messages.c.role == "user",
            ).limit(1)).first()
            db.execute(insert(chat_messages), [
                {
                    "id": user_message_id, "user_id": user_id, "session_id": session_id,
                    "role": "user", "status": "completed", "content": content,
                    "include_public": include_public,
                    "model": None, "grounding": None, "citations": [], "error_code": None,
                    "created_at": user_created_at, "completed_at": user_created_at,
                },
                {
                    "id": assistant_message_id, "user_id": user_id, "session_id": session_id,
                    "role": "assistant", "status": "generating", "content": "",
                    "include_public": include_public,
                    "model": model, "grounding": None, "citations": [], "error_code": None,
                    "created_at": assistant_created_at, "completed_at": None,
                },
            ])
            updates = {"updated_at": assistant_created_at}
            if not has_user_message and session["title"] == "新对话":
                normalized = " ".join(content.split())
                updates["title"] = normalized[:30] + ("…" if len(normalized) > 30 else "")
            db.execute(update(chat_sessions).where(chat_sessions.c.id == session_id).values(**updates))
        user_message = self.get_chat_message(user_id, user_message_id)
        assistant_message = self.get_chat_message(user_id, assistant_message_id)
        assert user_message is not None and assistant_message is not None
        return user_message, assistant_message

    def complete_chat_message(
        self, user_id: str, message_id: str, *, content: str,
        grounding: str, citations: list[dict],
    ) -> dict | None:
        completed_at = now_utc()
        with self.engine.begin() as db:
            row = db.execute(select(chat_messages.c.session_id).where(
                chat_messages.c.id == message_id,
                chat_messages.c.user_id == user_id,
                chat_messages.c.role == "assistant",
                chat_messages.c.status == "generating",
            )).first()
            if not row:
                return None
            db.execute(update(chat_messages).where(chat_messages.c.id == message_id).values(
                status="completed", content=content, grounding=grounding,
                citations=citations, error_code=None, completed_at=completed_at,
            ))
            db.execute(update(chat_sessions).where(chat_sessions.c.id == row.session_id).values(
                updated_at=completed_at,
            ))
        return self.get_chat_message(user_id, message_id)

    def fail_chat_message(self, user_id: str, message_id: str, error_code: str, *, cancelled: bool = False) -> dict | None:
        with self.engine.begin() as db:
            result = db.execute(update(chat_messages).where(
                chat_messages.c.id == message_id,
                chat_messages.c.user_id == user_id,
                chat_messages.c.role == "assistant",
                chat_messages.c.status == "generating",
            ).values(
                status="cancelled" if cancelled else "failed",
                error_code=error_code, completed_at=now_utc(),
            ))
            if result.rowcount != 1:
                return None
        return self.get_chat_message(user_id, message_id)

    def retry_chat_message(self, user_id: str, message_id: str) -> tuple[dict, dict] | None:
        with self.engine.begin() as db:
            assistant = db.execute(select(chat_messages).where(
                chat_messages.c.id == message_id,
                chat_messages.c.user_id == user_id,
                chat_messages.c.role == "assistant",
                chat_messages.c.status.in_(("failed", "cancelled")),
            ).with_for_update()).mappings().first()
            if not assistant:
                return None
            if db.execute(select(chat_messages.c.id).where(
                chat_messages.c.session_id == assistant["session_id"],
                chat_messages.c.status == "generating",
            ).limit(1)).first():
                raise ChatSessionBusy()
            user_message = db.execute(select(chat_messages).where(
                chat_messages.c.session_id == assistant["session_id"],
                chat_messages.c.user_id == user_id,
                chat_messages.c.role == "user",
                chat_messages.c.created_at <= assistant["created_at"],
            ).order_by(chat_messages.c.created_at.desc(), chat_messages.c.id.desc()).limit(1)).mappings().first()
            if not user_message:
                return None
            db.execute(update(chat_messages).where(chat_messages.c.id == message_id).values(
                status="generating", content="", grounding=None, citations=[],
                error_code=None, completed_at=None,
            ))
        retried = self.get_chat_message(user_id, message_id)
        assert retried is not None
        return dict(user_message), retried

    def fail_interrupted_chat_messages(self) -> int:
        with self.engine.begin() as db:
            result = db.execute(update(chat_messages).where(
                chat_messages.c.role == "assistant",
                chat_messages.c.status == "generating",
            ).values(status="failed", error_code="CHAT_INTERRUPTED", completed_at=now_utc()))
            return result.rowcount


class DocumentVersionConflict(RuntimeError):
    def __init__(self, current_version: int):
        super().__init__("Document version is stale")
        self.current_version = current_version


class ChatSessionBusy(RuntimeError):
    pass
