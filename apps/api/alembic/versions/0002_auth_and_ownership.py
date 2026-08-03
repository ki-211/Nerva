"""Add email authentication and strict per-user ownership."""

from alembic import op
import sqlalchemy as sa

from app.store import metadata


revision = "0002"
down_revision = "0001"

OWNED_TABLES = (
    "sources", "documents", "document_versions", "change_sets",
    "change_items", "knowledge_events",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "sources" not in inspector.get_table_names():
        metadata.create_all(bind)
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
