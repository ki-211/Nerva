import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index,
    Integer, MetaData, String, Table, Text, UniqueConstraint, create_engine,
    insert, select, update,
)
from sqlalchemy.engine import URL
from sqlalchemy.dialects.postgresql import JSONB

from .ai import MergeProposal


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


metadata = MetaData()

sources = Table(
    "sources", metadata,
    Column("id", String(40), primary_key=True),
    Column("kind", String(30), nullable=False),
    Column("title", String(160)),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

documents = Table(
    "documents", metadata,
    Column("id", String(40), primary_key=True),
    Column("title", String(160), nullable=False),
    Column("markdown", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("version >= 1", name="ck_documents_version"),
)

document_versions = Table(
    "document_versions", metadata,
    Column("id", String(40), primary_key=True),
    Column("document_id", String(40), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("markdown", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("version >= 1", name="ck_document_versions_version"),
    UniqueConstraint("document_id", "version", name="uq_document_version"),
)

change_sets = Table(
    "change_sets", metadata,
    Column("id", String(40), primary_key=True),
    Column("source_id", String(40), ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False),
    Column("status", String(30), nullable=False),
    Column("summary", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "status IN ('proposed', 'applied', 'partially_applied', 'rejected')",
        name="ck_change_sets_status",
    ),
)

change_items = Table(
    "change_items", metadata,
    Column("id", String(40), primary_key=True),
    Column("change_set_id", String(40), ForeignKey("change_sets.id", ondelete="CASCADE"), nullable=False),
    Column("operation", String(40), nullable=False),
    Column("target_document_id", String(40), ForeignKey("documents.id", ondelete="SET NULL")),
    Column("target_title", String(160), nullable=False),
    Column("reason", Text, nullable=False),
    Column("before_text", Text),
    Column("after_text", Text, nullable=False),
    Column("evidence", Text, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("accepted", Boolean),
    CheckConstraint(
        "operation IN ('CREATE_DOCUMENT', 'ADD_BLOCK', 'UPDATE_BLOCK', 'MOVE_BLOCK', "
        "'ADD_RELATION', 'MARK_DUPLICATE', 'REPORT_CONFLICT')",
        name="ck_change_items_operation",
    ),
    CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_change_items_confidence"),
)

knowledge_events = Table(
    "knowledge_events", metadata,
    Column("id", String(40), primary_key=True),
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

Index("idx_documents_updated_at", documents.c.updated_at.desc())
Index("idx_document_versions_document", document_versions.c.document_id, document_versions.c.version.desc())
Index("idx_change_sets_source", change_sets.c.source_id)
Index("idx_change_sets_status_created", change_sets.c.status, change_sets.c.created_at.desc())
Index("idx_change_items_change_set", change_items.c.change_set_id)
Index("idx_change_items_target_document", change_items.c.target_document_id)
Index("idx_knowledge_events_created_at", knowledge_events.c.created_at.desc())


class Store:
    """SQLAlchemy repository. Production uses PostgreSQL; tests use temporary SQLite."""

    def __init__(self, database_url: str | URL):
        self.engine = create_engine(database_url, pool_pre_ping=True)
        metadata.create_all(self.engine)

    def close(self) -> None:
        self.engine.dispose()

    def list_documents(self) -> list[dict]:
        with self.engine.connect() as db:
            rows = db.execute(select(documents).order_by(documents.c.updated_at.desc())).mappings()
            return [dict(row) for row in rows]

    def create_change_set(self, kind: str, content: str, title: str | None, proposal: MergeProposal) -> dict:
        source_id, change_set_id, item_id, created_at = new_id("src"), new_id("chg"), new_id("item"), now_utc()
        summary = "建议创建新知识文档" if proposal.operation == "CREATE_DOCUMENT" else f"建议合并到《{proposal.target_title}》"
        with self.engine.begin() as db:
            db.execute(insert(sources).values(id=source_id, kind=kind, title=title, content=content, created_at=created_at))
            db.execute(insert(change_sets).values(id=change_set_id, source_id=source_id, status="proposed", summary=summary, created_at=created_at))
            db.execute(insert(change_items).values(
                id=item_id, change_set_id=change_set_id, operation=proposal.operation,
                target_document_id=proposal.target_document_id, target_title=proposal.target_title,
                reason=proposal.reason, before_text=proposal.before, after_text=proposal.after,
                evidence=proposal.evidence, confidence=proposal.confidence,
            ))
        result = self.get_change_set(change_set_id)
        assert result is not None
        return result

    def get_change_set(self, change_set_id: str) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(select(change_sets).where(change_sets.c.id == change_set_id)).mappings().first()
            if not row:
                return None
            result = dict(row)
            items = db.execute(select(change_items).where(change_items.c.change_set_id == change_set_id)).mappings()
            result["items"] = [{
                "id": item["id"], "operation": item["operation"],
                "target_document_id": item["target_document_id"], "target_title": item["target_title"],
                "reason": item["reason"], "before": item["before_text"], "after": item["after_text"],
                "evidence": item["evidence"], "confidence": item["confidence"],
            } for item in items]
            return result

    def apply_change_set(self, change_set_id: str, accepted_ids: list[str] | None) -> dict | None:
        change_set = self.get_change_set(change_set_id)
        if not change_set or change_set["status"] != "proposed":
            return None
        allowed = set(accepted_ids) if accepted_ids is not None else {item["id"] for item in change_set["items"]}
        affected: list[str] = []
        accepted = 0
        created_at = now_utc()

        with self.engine.begin() as db:
            for item in change_set["items"]:
                is_accepted = item["id"] in allowed
                db.execute(update(change_items).where(change_items.c.id == item["id"]).values(accepted=is_accepted))
                if not is_accepted:
                    continue
                accepted += 1
                if item["operation"] == "CREATE_DOCUMENT":
                    document_id = new_id("doc")
                    markdown = item["after"]
                    db.execute(insert(documents).values(
                        id=document_id, title=item["target_title"], markdown=markdown,
                        version=1, created_at=created_at, updated_at=created_at,
                    ))
                    db.execute(insert(document_versions).values(
                        id=new_id("ver"), document_id=document_id, version=1,
                        markdown=markdown, reason=item["reason"], created_at=created_at,
                    ))
                    affected.append(item["target_title"])
                elif item["operation"] == "ADD_BLOCK" and item["target_document_id"]:
                    current = db.execute(
                        select(documents).where(documents.c.id == item["target_document_id"]).with_for_update()
                    ).mappings().first()
                    if current:
                        version = current["version"] + 1
                        markdown = current["markdown"].rstrip() + "\n\n" + item["after"].strip() + "\n"
                        db.execute(update(documents).where(documents.c.id == current["id"]).values(
                            markdown=markdown, version=version, updated_at=created_at,
                        ))
                        db.execute(insert(document_versions).values(
                            id=new_id("ver"), document_id=current["id"], version=version,
                            markdown=markdown, reason=item["reason"], created_at=created_at,
                        ))
                        affected.append(current["title"])

            total = len(change_set["items"])
            status = "applied" if accepted == total else "partially_applied"
            db.execute(update(change_sets).where(change_sets.c.id == change_set_id).values(status=status))
            db.execute(insert(knowledge_events).values(
                id=new_id("evt"), change_set_id=change_set_id, title="知识库已成长",
                summary=f"接受 {accepted} 项变更，影响 {len(affected)} 个文档",
                affected_documents=affected, accepted_count=accepted,
                rejected_count=total - accepted, created_at=created_at,
            ))
        return self.get_change_set(change_set_id)

    def list_events(self) -> list[dict]:
        with self.engine.connect() as db:
            rows = db.execute(select(knowledge_events).order_by(knowledge_events.c.created_at.desc())).mappings()
            return [dict(row) for row in rows]
