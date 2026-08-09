"""Add email authentication and strict per-user ownership."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002"
down_revision = "0001"

OWNED_TABLES = (
    "sources", "documents", "document_versions", "change_sets",
    "change_items", "knowledge_events",
)


def _create_empty_schema(bind) -> None:
    """Create a frozen schema through revision 0007 for a brand-new database.

    Later revisions must never leak into this historical bootstrap. Revisions
    0003..0007 are intentionally idempotent and will inspect this schema before
    0008 and newer revisions add their own tables.
    """
    baseline = sa.MetaData()
    users = sa.Table(
        "users", baseline,
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
    )
    sessions = sa.Table(
        "sessions", baseline,
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    email_codes = sa.Table(
        "email_verification_codes", baseline,
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resend_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("attempts >= 0", name="ck_email_codes_attempts"),
    )
    sources = sa.Table(
        "sources", baseline,
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("title", sa.String(160)),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("processing_status", sa.String(30), nullable=False),
        sa.Column("ai_provider", sa.String(40)),
        sa.Column("ai_model", sa.String(160)),
        sa.Column("prompt_version", sa.String(80)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.Text),
        sa.Column("processing_stage", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("processing_started_at", sa.DateTime(timezone=True)),
        sa.Column("total_inputs", sa.Integer, nullable=False, server_default="0"),
        sa.Column("processed_inputs", sa.Integer, nullable=False, server_default="0"),
        sa.Column("covered_inputs", sa.Integer, nullable=False, server_default="0"),
        sa.Column("extraction_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "pending_supersedes_change_set_id", sa.String(40),
            sa.ForeignKey(
                "change_sets.id", ondelete="SET NULL",
                name="fk_sources_pending_supersedes", use_alter=True,
            ),
        ),
        sa.Column("pending_analysis_instruction", sa.Text),
        sa.Column("ocr_model", sa.String(160)),
        sa.Column("ocr_prompt_version", sa.String(80)),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "processing_status IN ('received', 'processing', 'proposed', 'failed')",
            name="ck_sources_processing_status",
        ),
        sa.CheckConstraint(
            "processing_stage IN ('queued', 'ocr', 'extracting', 'coverage_repair', "
            "'retrieving', 'planning', 'complete', 'failed')",
            name="ck_sources_processing_stage",
        ),
        sa.CheckConstraint("total_inputs >= 0", name="ck_sources_total_inputs"),
        sa.CheckConstraint(
            "processed_inputs >= 0 AND processed_inputs <= total_inputs",
            name="ck_sources_processed_inputs",
        ),
        sa.CheckConstraint(
            "covered_inputs >= 0 AND covered_inputs <= total_inputs",
            name="ck_sources_covered_inputs",
        ),
        sa.CheckConstraint(
            "extraction_attempts >= 0 AND extraction_attempts <= 2",
            name="ck_sources_extraction_attempts",
        ),
    )
    units = sa.Table(
        "knowledge_units", baseline,
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String(40), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("input_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("subject", sa.String(160), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("source_span", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_knowledge_units_confidence"),
        sa.CheckConstraint("input_index >= 0", name="ck_knowledge_units_input_index"),
    )
    documents = sa.Table(
        "documents", baseline,
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("markdown", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_documents_version"),
    )
    versions = sa.Table(
        "document_versions", baseline,
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.String(40), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("markdown", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_document_versions_version"),
        sa.UniqueConstraint("document_id", "version", name="uq_document_version"),
    )
    change_sets = sa.Table(
        "change_sets", baseline,
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String(40), sa.ForeignKey("sources.id", ondelete="RESTRICT")),
        sa.Column("origin", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("supersedes_change_set_id", sa.String(40), sa.ForeignKey("change_sets.id", ondelete="SET NULL")),
        sa.Column("analysis_instruction", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('proposed', 'applied', 'partially_applied', 'rejected', 'superseded')",
            name="ck_change_sets_status",
        ),
        sa.CheckConstraint(
            "origin IN ('ai_ingestion', 'manual_edit')", name="ck_change_sets_origin",
        ),
    )
    items = sa.Table(
        "change_items", baseline,
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("change_set_id", sa.String(40), sa.ForeignKey("change_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation", sa.String(40), nullable=False),
        sa.Column("target_document_id", sa.String(40), sa.ForeignKey("documents.id", ondelete="SET NULL")),
        sa.Column("target_title", sa.String(160), nullable=False),
        sa.Column("before_title", sa.String(160)),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("before_text", sa.Text),
        sa.Column("after_text", sa.Text, nullable=False),
        sa.Column("evidence", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("accepted", sa.Boolean),
        sa.CheckConstraint(
            "operation IN ('CREATE_DOCUMENT', 'ADD_BLOCK', 'UPDATE_BLOCK', 'MOVE_BLOCK', "
            "'ADD_RELATION', 'MARK_DUPLICATE', 'REPORT_CONFLICT', 'UPDATE_DOCUMENT')",
            name="ck_change_items_operation",
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_change_items_confidence"),
    )
    events = sa.Table(
        "knowledge_events", baseline,
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("change_set_id", sa.String(40), sa.ForeignKey("change_sets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column(
            "affected_documents",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False,
        ),
        sa.Column("accepted_count", sa.Integer, nullable=False),
        sa.Column("rejected_count", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("accepted_count >= 0", name="ck_events_accepted_count"),
        sa.CheckConstraint("rejected_count >= 0", name="ck_events_rejected_count"),
    )

    sa.Index("idx_sessions_user", sessions.c.user_id, sessions.c.expires_at.desc())
    sa.Index("idx_email_codes_email_created", email_codes.c.email, email_codes.c.created_at.desc())
    sa.Index("idx_sources_user", sources.c.user_id, sources.c.created_at.desc())
    sa.Index("idx_sources_user_status", sources.c.user_id, sources.c.processing_status, sources.c.created_at.desc())
    sa.Index("idx_sources_user_stage", sources.c.user_id, sources.c.processing_stage, sources.c.created_at.desc())
    sa.Index("idx_knowledge_units_source", units.c.source_id)
    sa.Index("idx_knowledge_units_source_input", units.c.source_id, units.c.input_index)
    sa.Index("idx_knowledge_units_user", units.c.user_id, units.c.created_at.desc())
    sa.Index("idx_documents_user_updated", documents.c.user_id, documents.c.updated_at.desc())
    sa.Index("idx_documents_updated_at", documents.c.updated_at.desc())
    sa.Index("idx_document_versions_document", versions.c.document_id, versions.c.version.desc())
    sa.Index("idx_change_sets_source", change_sets.c.source_id)
    sa.Index("idx_change_sets_status_created", change_sets.c.status, change_sets.c.created_at.desc())
    sa.Index("idx_change_items_change_set", items.c.change_set_id)
    sa.Index("idx_change_items_target_document", items.c.target_document_id)
    sa.Index("idx_knowledge_events_created_at", events.c.created_at.desc())
    sa.Index("idx_knowledge_events_user_created", events.c.user_id, events.c.created_at.desc())
    baseline.create_all(bind)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "sources" not in inspector.get_table_names():
        _create_empty_schema(bind)
        return

    counts = {table: bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one() for table in OWNED_TABLES}

    existing_tables = set(inspector.get_table_names())
    if "users" not in existing_tables:
        op.create_table(
            "users",
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("email", sa.String(320), nullable=False, unique=True),
            sa.Column("display_name", sa.String(80), nullable=False),
            sa.Column("password_hash", sa.Text(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
        )
    if "sessions" not in existing_tables:
        op.create_table(
            "sessions",
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True)),
        )
        op.create_index("idx_sessions_user", "sessions", ["user_id", sa.text("expires_at DESC")])
    if "email_verification_codes" not in existing_tables:
        op.create_table(
            "email_verification_codes",
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("email", sa.String(320), nullable=False),
            sa.Column("code_hash", sa.String(64), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resend_after", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True)),
            sa.CheckConstraint("attempts >= 0", name="ck_email_codes_attempts"),
        )
        op.create_index("idx_email_codes_email_created", "email_verification_codes", ["email", sa.text("created_at DESC")])

    if any(counts.values()):
        bind.execute(sa.text("""
            INSERT INTO users (id, email, display_name, password_hash, status, created_at, updated_at)
            VALUES ('usr_legacy_local_migration', 'legacy-migration@nerva.invalid',
                    '待认领的旧数据', 'disabled-no-password', 'disabled', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """))

    for table in OWNED_TABLES:
        op.add_column(table, sa.Column("user_id", sa.String(40), nullable=True))
        op.create_foreign_key(f"fk_{table}_user_id", table, "users", ["user_id"], ["id"], ondelete="CASCADE")
        if counts[table]:
            bind.execute(sa.text(f"UPDATE {table} SET user_id = 'usr_legacy_local_migration' WHERE user_id IS NULL"))
        op.alter_column(table, "user_id", nullable=False)

    op.create_index("idx_sources_user", "sources", ["user_id", sa.text("created_at DESC")])
    op.create_index("idx_documents_user_updated", "documents", ["user_id", sa.text("updated_at DESC")])
    op.create_index("idx_knowledge_events_user_created", "knowledge_events", ["user_id", sa.text("created_at DESC")])


def downgrade() -> None:
    for name, table in (
        ("idx_knowledge_events_user_created", "knowledge_events"),
        ("idx_documents_user_updated", "documents"),
        ("idx_sources_user", "sources"),
    ):
        op.drop_index(name, table_name=table)
    for table in reversed(OWNED_TABLES):
        op.drop_constraint(f"fk_{table}_user_id", table, type_="foreignkey")
        op.drop_column(table, "user_id")
    op.drop_table("email_verification_codes")
    op.drop_table("sessions")
    op.drop_table("users")
