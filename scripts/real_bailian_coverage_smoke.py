"""Re-run a persisted multi-image OCR source in a disposable DB without printing OCR text."""

import tempfile
from pathlib import Path

from sqlalchemy import select

from apps.api.app import main as api_main
from apps.api.app.ai import AIProviderError, BailianAI
from apps.api.app.settings import settings
from apps.api.app.store import Store, knowledge_units, sources


def main() -> None:
    actual = Store(settings.sqlalchemy_url(), create_schema=False)
    with actual.engine.connect() as db:
        source = db.execute(select(sources).where(
            sources.c.kind == "image",
            sources.c.total_inputs >= 2,
        ).order_by(sources.c.created_at.desc()).limit(1)).mappings().first()
    if not source:
        raise SystemExit("No persisted multi-image source is available")

    with tempfile.TemporaryDirectory(prefix="nerva-coverage-smoke-") as tempdir:
        isolated = Store(f"sqlite+pysqlite:///{(Path(tempdir) / 'coverage.db').as_posix()}")
        previous_store, previous_ai = api_main.store, api_main.ai
        try:
            user = isolated.create_user("coverage-smoke@nerva.invalid", "Coverage Smoke")
            copied = isolated.create_image_source(
                user["id"], title=source["title"], total_inputs=source["total_inputs"],
                ocr_model=source["ocr_model"] or "persisted-ocr",
                ocr_prompt_version=source["ocr_prompt_version"] or "ocr-v1",
            )
            isolated.start_image_ocr(user["id"], copied["id"])
            isolated.save_ocr_content(user["id"], copied["id"], source["content"])
            api_main.store, api_main.ai = isolated, BailianAI()
            draft = api_main.run_knowledge_pipeline(user["id"], copied["id"])
            processing = isolated.get_source_processing(user["id"], copied["id"])
            with isolated.engine.connect() as db:
                unit_rows = db.execute(select(
                    knowledge_units.c.input_index, knowledge_units.c.subject,
                ).where(knowledge_units.c.source_id == copied["id"]).order_by(
                    knowledge_units.c.input_index,
                )).all()
            print({
                "source_id": source["id"],
                "covered_inputs": processing["covered_inputs"],
                "total_inputs": processing["total_inputs"],
                "extraction_attempts": processing["extraction_attempts"],
                "unit_counts": {
                    index: sum(1 for row_index, _ in unit_rows if row_index == index)
                    for index in sorted({row_index for row_index, _ in unit_rows})
                },
                "subjects": [subject for _, subject in unit_rows],
                "draft_titles": [item["target_title"] for item in draft["items"]],
                "draft_status": draft["status"],
            })
        except AIProviderError as exc:
            print({
                "error": exc.code,
                "upstream_status": exc.upstream_status,
                "upstream_code": exc.upstream_code,
                "request_id": exc.request_id,
            })
            raise SystemExit(1) from exc
        finally:
            api_main.store, api_main.ai = previous_store, previous_ai
            isolated.close()
            actual.close()


if __name__ == "__main__":
    main()
