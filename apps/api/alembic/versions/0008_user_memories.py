"""Add user_memories table for personalization."""

from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.create_table(
        'user_memories',
        sa.Column('id', sa.String(40), primary_key=True),
        sa.Column('user_id', sa.String(40), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('scope', sa.String(30), nullable=False),
        sa.Column('scope_ref', sa.String(160), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('confidence', sa.Float, nullable=False, server_default='1.0'),
        sa.Column('origin', sa.String(20), nullable=False),
        sa.Column('use_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('style', 'topic_split', 'domain', 'naming', 'merge_preference')",
            name='ck_memories_kind'
        ),
        sa.CheckConstraint(
            "scope IN ('global', 'document', 'topic')",
            name='ck_memories_scope'
        ),
        sa.CheckConstraint(
            "status IN ('active', 'candidate', 'suppressed')",
            name='ck_memories_status'
        ),
        sa.CheckConstraint(
            "origin IN ('user_explicit', 'ai_inferred', 'ai_observed')",
            name='ck_memories_origin'
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name='ck_memories_confidence'),
        sa.CheckConstraint("use_count >= 0", name='ck_memories_use_count'),
    )

    op.create_index(
        'idx_memories_user_active',
        'user_memories',
        ['user_id', 'status', 'kind']
    )
    op.create_index(
        'idx_memories_user_created',
        'user_memories',
        ['user_id', 'created_at']
    )


def downgrade() -> None:
    op.drop_index('idx_memories_user_created')
    op.drop_index('idx_memories_user_active')
    op.drop_table('user_memories')
