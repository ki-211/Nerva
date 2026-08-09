"""Add security and administrator audit events."""

from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("actor_user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("actor_role", sa.String(20), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_id", sa.String(128)),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("client_type", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "actor_role IN ('anonymous', 'user', 'admin', 'system')",
            name="ck_audit_actor_role",
        ),
        sa.CheckConstraint(
            "outcome IN ('success', 'failure', 'denied', 'locked')",
            name="ck_audit_outcome",
        ),
    )
    op.create_index("idx_audit_events_created", "audit_events", [sa.text("created_at DESC")])
    op.create_index("idx_audit_events_actor_created", "audit_events", ["actor_user_id", sa.text("created_at DESC")])
    op.create_index("idx_audit_events_action_target", "audit_events", ["action", "target_id", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_index("idx_audit_events_action_target", table_name="audit_events")
    op.drop_index("idx_audit_events_actor_created", table_name="audit_events")
    op.drop_index("idx_audit_events_created", table_name="audit_events")
    op.drop_table("audit_events")
