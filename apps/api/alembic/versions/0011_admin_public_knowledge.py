"""Add administrator credentials and shared public documents."""

from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if "username" not in _columns("users"):
        op.add_column("users", sa.Column("username", sa.String(80), nullable=True))
    if "password_hash" not in _columns("users"):
        op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
    if "role" not in _columns("users"):
        op.add_column("users", sa.Column("role", sa.String(20), nullable=False, server_default="user"))
    if "visibility" not in _columns("documents"):
        op.add_column("documents", sa.Column("visibility", sa.String(20), nullable=False, server_default="private"))
    if "include_public" not in _columns("chat_messages"):
        op.add_column("chat_messages", sa.Column("include_public", sa.Boolean(), nullable=False, server_default=sa.true()))

    inspector = sa.inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("users")}
    if "uq_users_username" not in indexes:
        op.create_index("uq_users_username", "users", ["username"], unique=True)
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("documents")}
    if "idx_documents_visibility_updated" not in indexes:
        op.create_index(
            "idx_documents_visibility_updated", "documents",
            ["visibility", sa.text("updated_at DESC")],
        )


def downgrade() -> None:
    bind = op.get_bind()
    for name, table in (
        ("idx_documents_visibility_updated", "documents"),
        ("uq_users_username", "users"),
    ):
        if name in {item["name"] for item in sa.inspect(bind).get_indexes(table)}:
            op.drop_index(name, table_name=table)
    columns = _columns("chat_messages")
    if "include_public" in columns:
        op.drop_column("chat_messages", "include_public")
    columns = _columns("documents")
    if "visibility" in columns:
        op.drop_column("documents", "visibility")
    columns = _columns("users")
    for name in ("role", "password_hash", "username"):
        if name in columns:
            op.drop_column("users", name)
