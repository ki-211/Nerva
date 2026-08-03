"""Remove password credentials after switching to email code login."""

from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "password_hash" in columns:
        op.drop_column("users", "password_hash")


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "password_hash" not in columns:
        op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
