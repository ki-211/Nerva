"""Add current-version Markdown chunks and optional embeddings."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.String(40), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_version", sa.Integer, nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", sa.JSON().with_variant(postgresql.ARRAY(sa.REAL, dimensions=1), "postgresql"), nullable=True),
        sa.Column("embedding_model", sa.String(160)),
        sa.Column("embedding_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("document_version >= 1", name="ck_document_chunks_version"),
        sa.CheckConstraint("ordinal >= 0", name="ck_document_chunks_ordinal"),
        sa.CheckConstraint("embedding_status IN ('pending', 'ready', 'failed')", name="ck_document_chunks_embedding_status"),
        sa.UniqueConstraint("document_id", "document_version", "ordinal", name="uq_document_chunks_document_version_ordinal"),
    )
    op.create_index("idx_document_chunks_user", "document_chunks", ["user_id", "document_id"])
    op.create_index("idx_document_chunks_document_version", "document_chunks", ["document_id", "document_version", "ordinal"])
    op.create_index("idx_document_chunks_user_status", "document_chunks", ["user_id", "embedding_status"])


def downgrade() -> None:
    op.drop_index("idx_document_chunks_user_status", table_name="document_chunks")
    op.drop_index("idx_document_chunks_document_version", table_name="document_chunks")
    op.drop_index("idx_document_chunks_user", table_name="document_chunks")
    op.drop_table("document_chunks")
