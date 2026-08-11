"""Add per-user knowledge hub settings."""

from alembic import op
import sqlalchemy as sa


revision = "0014"
down_revision = "0013"


def upgrade() -> None:
    op.create_table(
        "knowledge_hub_settings",
        sa.Column(
            "user_id", sa.String(40),
            sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column(
            "personalization_enabled", sa.Boolean(),
            nullable=False, server_default=sa.true(),
        ),
        sa.Column(
            "auto_learning_enabled", sa.Boolean(),
            nullable=False, server_default=sa.true(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("knowledge_hub_settings")
