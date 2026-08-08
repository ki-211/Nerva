"""Add multi-input coverage and draft reprocessing lineage."""

from alembic import op
import sqlalchemy as sa


revision = "0007"
down_revision = "0006"


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    source_columns = _columns(bind, "sources")
    unit_columns = _columns(bind, "knowledge_units")
    set_columns = _columns(bind, "change_sets")

    if "covered_inputs" not in source_columns:
        op.add_column("sources", sa.Column("covered_inputs", sa.Integer(), nullable=True))
        bind.execute(sa.text("UPDATE sources SET covered_inputs = 0"))
        op.alter_column("sources", "covered_inputs", nullable=False)
    if "extraction_attempts" not in source_columns:
        op.add_column("sources", sa.Column("extraction_attempts", sa.Integer(), nullable=True))
        bind.execute(sa.text("UPDATE sources SET extraction_attempts = 0"))
        op.alter_column("sources", "extraction_attempts", nullable=False)
    if "pending_supersedes_change_set_id" not in source_columns:
        op.add_column("sources", sa.Column("pending_supersedes_change_set_id", sa.String(40), nullable=True))
        if bind.dialect.name == "postgresql":
            op.create_foreign_key(
                "fk_sources_pending_supersedes", "sources", "change_sets",
                ["pending_supersedes_change_set_id"], ["id"], ondelete="SET NULL",
            )
    if "pending_analysis_instruction" not in source_columns:
        op.add_column("sources", sa.Column("pending_analysis_instruction", sa.Text(), nullable=True))

    if "input_index" not in unit_columns:
        op.add_column("knowledge_units", sa.Column("input_index", sa.Integer(), nullable=True))
        bind.execute(sa.text("UPDATE knowledge_units SET input_index = 0"))
        op.alter_column("knowledge_units", "input_index", nullable=False)

    if "supersedes_change_set_id" not in set_columns:
        op.add_column("change_sets", sa.Column("supersedes_change_set_id", sa.String(40), nullable=True))
        if bind.dialect.name == "postgresql":
            op.create_foreign_key(
                "fk_change_sets_supersedes", "change_sets", "change_sets",
                ["supersedes_change_set_id"], ["id"], ondelete="SET NULL",
            )
    if "analysis_instruction" not in set_columns:
        op.add_column("change_sets", sa.Column("analysis_instruction", sa.Text(), nullable=True))

    if bind.dialect.name == "postgresql":
        inspector = sa.inspect(bind)
        source_constraints = {
            item["name"]: item["sqltext"] for item in inspector.get_check_constraints("sources")
        }
        stage_name = next((
            name for name, sql in source_constraints.items() if "processing_stage" in sql
        ), None)
        if stage_name and "coverage_repair" not in source_constraints[stage_name]:
            op.drop_constraint(stage_name, "sources", type_="check")
            op.create_check_constraint(
                "ck_sources_processing_stage", "sources",
                "processing_stage IN ('queued', 'ocr', 'extracting', 'coverage_repair', "
                "'retrieving', 'planning', 'complete', 'failed')",
            )
        for name, expression in (
            ("ck_sources_covered_inputs", "covered_inputs >= 0 AND covered_inputs <= total_inputs"),
            ("ck_sources_extraction_attempts", "extraction_attempts >= 0 AND extraction_attempts <= 2"),
        ):
            if name not in source_constraints:
                op.create_check_constraint(name, "sources", expression)

        unit_constraints = {
            item["name"] for item in sa.inspect(bind).get_check_constraints("knowledge_units")
        }
        if "ck_knowledge_units_input_index" not in unit_constraints:
            op.create_check_constraint(
                "ck_knowledge_units_input_index", "knowledge_units", "input_index >= 0",
            )

        set_constraints = {
            item["name"]: item["sqltext"] for item in sa.inspect(bind).get_check_constraints("change_sets")
        }
        status_name = next((name for name, sql in set_constraints.items() if "status" in sql), None)
        if status_name and "superseded" not in set_constraints[status_name]:
            op.drop_constraint(status_name, "change_sets", type_="check")
            op.create_check_constraint(
                "ck_change_sets_status", "change_sets",
                "status IN ('proposed', 'applied', 'partially_applied', 'rejected', 'superseded')",
            )

    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("knowledge_units")}
    if "idx_knowledge_units_source_input" not in indexes:
        op.create_index(
            "idx_knowledge_units_source_input", "knowledge_units", ["source_id", "input_index"],
        )


def downgrade() -> None:
    op.drop_index("idx_knowledge_units_source_input", table_name="knowledge_units")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("fk_change_sets_supersedes", "change_sets", type_="foreignkey")
        op.drop_constraint("fk_sources_pending_supersedes", "sources", type_="foreignkey")
        op.drop_constraint("ck_knowledge_units_input_index", "knowledge_units", type_="check")
        op.drop_constraint("ck_sources_extraction_attempts", "sources", type_="check")
        op.drop_constraint("ck_sources_covered_inputs", "sources", type_="check")
        op.drop_constraint("ck_change_sets_status", "change_sets", type_="check")
        op.create_check_constraint(
            "ck_change_sets_status", "change_sets",
            "status IN ('proposed', 'applied', 'partially_applied', 'rejected')",
        )
        op.drop_constraint("ck_sources_processing_stage", "sources", type_="check")
        op.create_check_constraint(
            "ck_sources_processing_stage", "sources",
            "processing_stage IN ('queued', 'ocr', 'extracting', 'retrieving', 'planning', 'complete', 'failed')",
        )
    op.drop_column("change_sets", "analysis_instruction")
    op.drop_column("change_sets", "supersedes_change_set_id")
    op.drop_column("knowledge_units", "input_index")
    op.drop_column("sources", "pending_analysis_instruction")
    op.drop_column("sources", "pending_supersedes_change_set_id")
    op.drop_column("sources", "extraction_attempts")
    op.drop_column("sources", "covered_inputs")
