"""Run synthetic two-input coverage through the formal knowledge pipeline."""

import logging
import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.api.app import main as api_main
from apps.api.app.ai import AIProviderError, BailianAI
from apps.api.app.image_ingestion import combine_ocr_text
from apps.api.app.store import Store, knowledge_units


def main() -> None:
    if os.getenv("NERVA_RUN_REAL_BAILIAN_SMOKE") != "1":
        raise SystemExit("Set NERVA_RUN_REAL_BAILIAN_SMOKE=1 to run the real Bailian smoke")
    logging.disable(logging.CRITICAL)
    synthetic_ocr = combine_ocr_text(None, [
        "合成组件 Atlas 使用不可变列表保存发布批次；追加批次时创建新列表。",
        "合成数据库 Helios 的事务隔离级别固定为可重复读，失败后必须完整回滚。",
    ])
    with tempfile.TemporaryDirectory(prefix="nerva-coverage-smoke-") as tempdir:
        isolated = Store(f"sqlite+pysqlite:///{(Path(tempdir) / 'coverage.db').as_posix()}")
        previous_store, previous_ai = api_main.store, api_main.ai
        ai = BailianAI()
        try:
            user = isolated.create_user("coverage-smoke@nerva.invalid", "Coverage Smoke")
            source = isolated.create_image_source(
                user["id"], title="合成双输入覆盖", total_inputs=2,
                ocr_model="synthetic-input", ocr_prompt_version="synthetic-v1",
            )
            isolated.start_image_ocr(user["id"], source["id"])
            isolated.save_ocr_content(user["id"], source["id"], synthetic_ocr)
            api_main.store, api_main.ai = isolated, ai
            draft = api_main.run_knowledge_pipeline(user["id"], source["id"])
            processing = isolated.get_source_processing(user["id"], source["id"])
            with isolated.engine.connect() as db:
                input_indexes = list(db.execute(select(
                    knowledge_units.c.input_index,
                ).where(knowledge_units.c.source_id == source["id"])).scalars())
            unit_counts = {index: input_indexes.count(index) for index in sorted(set(input_indexes))}
            result = {
                "model": ai.model,
                "covered_inputs": processing["covered_inputs"],
                "total_inputs": processing["total_inputs"],
                "extraction_attempts": processing["extraction_attempts"],
                "unit_counts": unit_counts,
                "operations": [item["operation"] for item in draft["items"]],
                "draft_status": draft["status"],
                "complete_coverage": processing["covered_inputs"] == 2,
            }
            print(result)
            if not result["complete_coverage"]:
                raise SystemExit(1)
        except AIProviderError as exc:
            print({"error": exc.code, "upstream_status": exc.upstream_status})
            raise SystemExit(1) from exc
        finally:
            api_main.store, api_main.ai = previous_store, previous_ai
            isolated.close()


if __name__ == "__main__":
    main()
