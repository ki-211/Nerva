"""Add source processing lifecycle and extracted knowledge units."""

from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    source_columns = {column["name"] for column in inspector.get_columns("sources")}

    if "processing_status" not in source_columns:
        op.add_column("sources", sa.Column("processing_status", sa.String(30), nullable=True))
        bind.execute(sa.text("UPDATE sources SET processing_status = 'proposed'"))
        op.alter_column("sources", "processing_status", nullable=False)
    for name, column_type in (
        ("ai_provider", sa.String(40)),
        ("ai_model", sa.String(160)),
        ("prompt_version", sa.String(80)),
        ("error_code", sa.String(80)),
        ("error_message", sa.Text()),
        ("processed_at", sa.DateTime(timezone=True)),
    ):
        if name not in source_columns:
            op.add_column("sources", sa.Column(name, column_type, nullable=True))

    if bind.dialect.name == "postgresql":
        constraints = {item["name"] for item in inspector.get_check_constraints("sources")}
        if "ck_sources_processing_status" not in constraints:
            op.create_check_constraint(
                "ck_sources_processing_status", "sources",
                "processing_status IN ('received', 'processing', 'proposed', 'failed')",
            )

    if "knowledge_units" not in tables:
        op.create_table(
            "knowledge_units",
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_id", sa.String(40), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
            sa.Column("type", sa.String(40), nullable=False),
            sa.Column("subject", sa.String(160), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("source_span", sa.Text(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_knowledge_units_confidence"),
        )

    inspector = sa.inspect(bind)
    source_indexes = {item["name"] for item in inspector.get_indexes("sources")}
    if "idx_sources_user_status" not in source_indexes:
        op.create_index(
            "idx_sources_user_status", "sources",
            ["user_id", "processing_status", sa.text("created_at DESC")],
        )
    document_indexes = {item["name"] for item in inspector.get_indexes("documents")}
    if "idx_documents_updated_at" not in document_indexes:
        op.create_index("idx_documents_updated_at", "documents", [sa.text("updated_at DESC")])
    unit_indexes = {item["name"] for item in inspector.get_indexes("knowledge_units")}
    if "idx_knowledge_units_source" not in unit_indexes:
        op.create_index("idx_knowledge_units_source", "knowledge_units", ["source_id"])
    if "idx_knowledge_units_user" not in unit_indexes:
        op.create_index(
            "idx_knowledge_units_user", "knowledge_units",
            ["user_id", sa.text("created_at DESC")],
        )


def downgrade() -> None:
    op.drop_index("idx_knowledge_units_user", table_name="knowledge_units")
    op.drop_index("idx_knowledge_units_source", table_name="knowledge_units")
    op.drop_table("knowledge_units")
    op.drop_index("idx_sources_user_status", table_name="sources")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("ck_sources_processing_status", "sources", type_="check")
    for name in (
        "processed_at", "error_message", "error_code", "prompt_version",
        "ai_model", "ai_provider", "processing_status",
    ):
        op.drop_column("sources", name)
