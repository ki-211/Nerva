"""Add cross-session long-term memories and message references."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0015"
down_revision = "0014"


def upgrade() -> None:
    op.add_column(
        "knowledge_hub_settings",
        sa.Column("long_term_memory_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "chat_messages",
        sa.Column("memory_refs", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "research_messages",
        sa.Column("memory_refs", sa.JSON(), nullable=False, server_default="[]"),
    )

    op.create_table(
        "long_term_memories",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("subject", sa.String(160), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("source_channel", sa.String(20), nullable=False),
        sa.Column("source_session_id", sa.String(40)),
        sa.Column("source_message_id", sa.String(40)),
        sa.Column("conflict_memory_id", sa.String(40), sa.ForeignKey("long_term_memories.id", ondelete="SET NULL")),
        sa.Column("embedding", sa.JSON().with_variant(postgresql.ARRAY(sa.REAL, dimensions=1), "postgresql")),
        sa.Column("embedding_model", sa.String(160)),
        sa.Column("embedding_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("undo_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('person', 'project', 'decision', 'fact')", name="ck_long_term_memories_kind"),
        sa.CheckConstraint("status IN ('active', 'candidate', 'suppressed', 'pending_delete')", name="ck_long_term_memories_status"),
        sa.CheckConstraint("origin IN ('user_explicit', 'ai_inferred', 'manual')", name="ck_long_term_memories_origin"),
        sa.CheckConstraint("source_channel IN ('chat', 'research', 'manual', 'history')", name="ck_long_term_memories_source"),
        sa.CheckConstraint("embedding_status IN ('pending', 'ready', 'failed')", name="ck_long_term_memories_embedding_status"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_long_term_memories_confidence"),
        sa.CheckConstraint("use_count >= 0", name="ck_long_term_memories_use_count"),
    )
    op.create_index("idx_long_term_memories_user_status", "long_term_memories", ["user_id", "status", "kind"])
    op.create_index("idx_long_term_memories_user_updated", "long_term_memories", ["user_id", "updated_at"])

    op.create_table(
        "long_term_memory_mutations",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("memory_id", sa.String(40), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("before_state", sa.JSON(), nullable=False),
        sa.Column("after_state", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("undone_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action IN ('create', 'update', 'delete')", name="ck_long_term_memory_mutations_action"),
    )
    op.create_index("idx_long_term_memory_mutations_user_expiry", "long_term_memory_mutations", ["user_id", "expires_at"])

    op.create_table(
        "long_term_memory_events",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("memory_id", sa.String(40), sa.ForeignKey("long_term_memories.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('candidate_created', 'remembered', 'confirmed', 'ignored', 'corrected', 'forgotten', 'undo')",
            name="ck_long_term_memory_events_action",
        ),
    )
    op.create_index("idx_long_term_memory_events_user_created", "long_term_memory_events", ["user_id", "created_at"])

def downgrade() -> None:
    op.drop_index("idx_long_term_memory_events_user_created", table_name="long_term_memory_events")
    op.drop_table("long_term_memory_events")
    op.drop_index("idx_long_term_memory_mutations_user_expiry", table_name="long_term_memory_mutations")
    op.drop_table("long_term_memory_mutations")
    op.drop_index("idx_long_term_memories_user_updated", table_name="long_term_memories")
    op.drop_index("idx_long_term_memories_user_status", table_name="long_term_memories")
    op.drop_table("long_term_memories")
    op.drop_column("research_messages", "memory_refs")
    op.drop_column("chat_messages", "memory_refs")
    op.drop_column("knowledge_hub_settings", "long_term_memory_enabled")
