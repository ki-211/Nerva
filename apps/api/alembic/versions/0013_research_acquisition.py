"""Add persistent AI and web research sessions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0013"
down_revision = "0012"


def upgrade() -> None:
    op.create_table(
        "research_sessions",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "research_messages",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.String(40), sa.ForeignKey("research_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("requested_mode", sa.String(20)),
        sa.Column("basis", sa.String(20)),
        sa.Column("model", sa.String(160)),
        sa.Column("citations", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column(
            "ingestion_source_id", sa.String(40),
            sa.ForeignKey("sources.id", ondelete="SET NULL"), unique=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_research_messages_role"),
        sa.CheckConstraint(
            "status IN ('generating', 'completed', 'failed', 'cancelled')",
            name="ck_research_messages_status",
        ),
        sa.CheckConstraint(
            "requested_mode IS NULL OR requested_mode IN ('smart', 'web', 'ai')",
            name="ck_research_messages_requested_mode",
        ),
        sa.CheckConstraint(
            "basis IS NULL OR basis IN ('web', 'ai')",
            name="ck_research_messages_basis",
        ),
    )
    op.create_index(
        "idx_research_sessions_user_updated", "research_sessions", ["user_id", "updated_at"],
    )
    op.create_index(
        "idx_research_messages_session_created", "research_messages", ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_research_messages_session_created")
    op.drop_index("idx_research_sessions_user_updated")
    op.drop_table("research_messages")
    op.drop_table("research_sessions")
