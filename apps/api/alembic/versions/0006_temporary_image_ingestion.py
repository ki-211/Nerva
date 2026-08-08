"""Add temporary image ingestion processing state."""

from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("sources")}

    if "processing_stage" not in columns:
        op.add_column("sources", sa.Column("processing_stage", sa.String(30), nullable=True))
        bind.execute(sa.text("""
            UPDATE sources SET processing_stage = CASE
                WHEN processing_status = 'proposed' THEN 'complete'
                WHEN processing_status = 'failed' THEN 'failed'
                ELSE 'queued'
            END
        """))
        op.alter_column("sources", "processing_stage", nullable=False)
    if "processing_started_at" not in columns:
        op.add_column("sources", sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True))
    if "total_inputs" not in columns:
        op.add_column("sources", sa.Column("total_inputs", sa.Integer(), nullable=True))
        bind.execute(sa.text("UPDATE sources SET total_inputs = 0"))
        op.alter_column("sources", "total_inputs", nullable=False)
    if "processed_inputs" not in columns:
        op.add_column("sources", sa.Column("processed_inputs", sa.Integer(), nullable=True))
        bind.execute(sa.text("UPDATE sources SET processed_inputs = 0"))
        op.alter_column("sources", "processed_inputs", nullable=False)
    if "ocr_model" not in columns:
        op.add_column("sources", sa.Column("ocr_model", sa.String(160), nullable=True))
    if "ocr_prompt_version" not in columns:
        op.add_column("sources", sa.Column("ocr_prompt_version", sa.String(80), nullable=True))

    if bind.dialect.name == "postgresql":
        constraints = {item["name"] for item in sa.inspect(bind).get_check_constraints("sources")}
        if "ck_sources_processing_stage" not in constraints:
            op.create_check_constraint(
                "ck_sources_processing_stage", "sources",
                "processing_stage IN ('queued', 'ocr', 'extracting', 'retrieving', 'planning', 'complete', 'failed')",
            )
        if "ck_sources_total_inputs" not in constraints:
            op.create_check_constraint("ck_sources_total_inputs", "sources", "total_inputs >= 0")
        if "ck_sources_processed_inputs" not in constraints:
            op.create_check_constraint(
                "ck_sources_processed_inputs", "sources",
                "processed_inputs >= 0 AND processed_inputs <= total_inputs",
            )

    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("sources")}
    if "idx_sources_user_stage" not in indexes:
        op.create_index(
            "idx_sources_user_stage", "sources",
            ["user_id", "processing_stage", sa.text("created_at DESC")],
        )


def downgrade() -> None:
    op.drop_index("idx_sources_user_stage", table_name="sources")
    if op.get_bind().dialect.name == "postgresql":
        for name in (
            "ck_sources_processed_inputs", "ck_sources_total_inputs",
            "ck_sources_processing_stage",
        ):
            op.drop_constraint(name, "sources", type_="check")
    for name in (
        "ocr_prompt_version", "ocr_model", "processed_inputs", "total_inputs",
        "processing_started_at", "processing_stage",
    ):
        op.drop_column("sources", name)
