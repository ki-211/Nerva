"""Baseline for the knowledge schema that predates Alembic."""

revision = "0001"
down_revision = None


def upgrade() -> None:
    # Existing installations stamp this revision. Revision 0002 creates the
    # complete schema on a new database and upgrades an empty legacy database.
    pass


def downgrade() -> None:
    pass
