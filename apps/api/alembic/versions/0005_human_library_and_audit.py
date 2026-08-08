"""Add human document editing and complete change audit details."""

from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    inspector = sa.inspect(bind)
    version_columns = {column["name"] for column in inspector.get_columns("document_versions")}
    change_set_columns = {column["name"] for column in inspector.get_columns("change_sets")}
    change_item_columns = {column["name"] for column in inspector.get_columns("change_items")}

    if "title" not in version_columns:
        op.add_column("document_versions", sa.Column("title", sa.String(160), nullable=True))
        if dialect == "postgresql":
            bind.execute(sa.text(
                "UPDATE document_versions SET title = documents.title "
                "FROM documents WHERE document_versions.document_id = documents.id"
            ))
        else:
            bind.execute(sa.text(
                "UPDATE document_versions SET title = (SELECT documents.title FROM documents "
                "WHERE documents.id = document_versions.document_id)"
            ))
        op.alter_column("document_versions", "title", nullable=False)

    if "origin" not in change_set_columns:
        op.add_column(
            "change_sets",
            sa.Column("origin", sa.String(30), nullable=False, server_default="ai_ingestion"),
        )
        op.alter_column("change_sets", "origin", server_default=None)
    source_column = next(column for column in inspector.get_columns("change_sets") if column["name"] == "source_id")
    if not source_column["nullable"]:
        op.alter_column("change_sets", "source_id", existing_type=sa.String(40), nullable=True)
    if "before_title" not in change_item_columns:
        op.add_column("change_items", sa.Column("before_title", sa.String(160), nullable=True))

    if dialect == "postgresql":
        set_constraints = {
            constraint["name"] for constraint in sa.inspect(bind).get_check_constraints("change_sets")
        }
        if "ck_change_sets_origin" not in set_constraints:
            op.create_check_constraint(
                "ck_change_sets_origin", "change_sets",
                "origin IN ('ai_ingestion', 'manual_edit')",
            )
        operation_constraint = next((
            constraint["name"] for constraint in sa.inspect(bind).get_check_constraints("change_items")
            if "operation" in constraint["sqltext"]
        ), None)
        operation_sql = next((
            constraint["sqltext"] for constraint in sa.inspect(bind).get_check_constraints("change_items")
            if "operation" in constraint["sqltext"]
        ), "")
        if "UPDATE_DOCUMENT" not in operation_sql and operation_constraint:
            op.drop_constraint(operation_constraint, "change_items", type_="check")
        if "UPDATE_DOCUMENT" not in operation_sql:
            op.create_check_constraint(
                "ck_change_items_operation", "change_items",
                "operation IN ('CREATE_DOCUMENT', 'ADD_BLOCK', 'UPDATE_BLOCK', 'MOVE_BLOCK', "
                "'ADD_RELATION', 'MARK_DUPLICATE', 'REPORT_CONFLICT', 'UPDATE_DOCUMENT')",
            )
        bind.execute(sa.text("""
            UPDATE change_items AS item
            SET target_document_id = document.id
            FROM documents AS document
            WHERE item.operation = 'CREATE_DOCUMENT'
              AND item.target_document_id IS NULL
              AND item.accepted = TRUE
              AND item.user_id = document.user_id
              AND item.target_title = document.title
              AND (
                SELECT count(*) FROM documents AS candidate
                WHERE candidate.user_id = item.user_id
                  AND candidate.title = item.target_title
              ) = 1
        """))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        bind = op.get_bind()
        operation_constraint = next((
            constraint["name"] for constraint in sa.inspect(bind).get_check_constraints("change_items")
            if "operation" in constraint["sqltext"]
        ), None)
        if operation_constraint:
            op.drop_constraint(operation_constraint, "change_items", type_="check")
        op.create_check_constraint(
            "ck_change_items_operation", "change_items",
            "operation IN ('CREATE_DOCUMENT', 'ADD_BLOCK', 'UPDATE_BLOCK', 'MOVE_BLOCK', "
            "'ADD_RELATION', 'MARK_DUPLICATE', 'REPORT_CONFLICT')",
        )
        op.drop_constraint("ck_change_sets_origin", "change_sets", type_="check")
    op.drop_column("change_items", "before_title")
    op.alter_column("change_sets", "source_id", existing_type=sa.String(40), nullable=False)
    op.drop_column("change_sets", "origin")
    op.drop_column("document_versions", "title")
