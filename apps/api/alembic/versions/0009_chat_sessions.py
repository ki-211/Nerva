"""Add persistent knowledge-chat sessions and messages."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.String(40), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("model", sa.String(160)),
        sa.Column("grounding", sa.String(30)),
        sa.Column("citations", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_chat_messages_role"),
        sa.CheckConstraint(
            "status IN ('generating', 'completed', 'failed', 'cancelled')",
            name="ck_chat_messages_status",
        ),
        sa.CheckConstraint(
            "grounding IS NULL OR grounding IN ('knowledge', 'knowledge_plus_general', 'general', 'insufficient')",
            name="ck_chat_messages_grounding",
        ),
    )
    op.create_index("idx_chat_sessions_user_updated", "chat_sessions", ["user_id", "updated_at"])
    op.create_index("idx_chat_messages_session_created", "chat_messages", ["session_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_chat_messages_session_created")
    op.drop_index("idx_chat_sessions_user_updated")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
