"""Align long-term memory JSON storage with PostgreSQL JSONB conventions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0016"
down_revision = "0015"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column in (
        ("chat_messages", "memory_refs"),
        ("research_messages", "memory_refs"),
        ("long_term_memory_mutations", "before_state"),
        ("long_term_memory_mutations", "after_state"),
    ):
        op.alter_column(
            table, column, type_=postgresql.JSONB(),
            postgresql_using=f"{column}::jsonb",
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column in (
        ("chat_messages", "memory_refs"),
        ("research_messages", "memory_refs"),
        ("long_term_memory_mutations", "before_state"),
        ("long_term_memory_mutations", "after_state"),
    ):
        op.alter_column(
            table, column, type_=sa.JSON(),
            postgresql_using=f"{column}::json",
        )
