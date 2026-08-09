"""Run a synthetic real Bailian text smoke without printing content or credentials."""

import os
import sys
import tempfile
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.api.app.ai import AIProviderError, BailianAI, retrieve_candidates
from apps.api.app.logging_config import configure_logging
from apps.api.app.prompts import EXTRACT_PROMPT_VERSION, MERGE_PROMPT_VERSION
from apps.api.app.store import Store


def main() -> None:
    if os.getenv("NERVA_RUN_REAL_BAILIAN_SMOKE") != "1":
        raise SystemExit("Set NERVA_RUN_REAL_BAILIAN_SMOKE=1 to run the real Bailian smoke")
    configure_logging()
    logging.disable(logging.CRITICAL)
    ai = BailianAI()
    content = "合成系统 Orion 的知识变更必须先生成待审批草案，审批通过后才修改正式文档。"
    title = "合成审批规则"
    with tempfile.TemporaryDirectory() as tempdir:
        store = Store(f"sqlite+pysqlite:///{(Path(tempdir) / 'smoke.db').as_posix()}")
        try:
            user = store.create_user("bailian-smoke@nerva.invalid", "Bailian Smoke")
            source = store.create_source(user["id"], "text", content, title)
            store.claim_source_for_processing(
                user["id"], source["id"], provider=ai.provider, model=ai.model,
                prompt_version=f"{EXTRACT_PROMPT_VERSION}+{MERGE_PROMPT_VERSION}",
            )
            extraction = ai.extract(content, title)
            store.save_extraction(user["id"], source["id"], extraction)
            candidates = retrieve_candidates(content, title, store.list_documents(user["id"]), limit=8)
            proposals = ai.plan(extraction, candidates, title)
            draft = store.create_change_set_for_source(user["id"], source["id"], proposals)
            applied = store.apply_change_set(user["id"], draft["id"], None)
            print({
                "model": ai.model,
                "units": len(extraction.units), "changes": len(proposals),
                "operations": [item.operation for item in proposals],
                "draft_status": draft["status"], "applied_status": applied["status"],
                "documents": len(store.list_documents(user["id"])),
                "events": len(store.list_events(user["id"])),
            })
        except AIProviderError as exc:
            print({"error": exc.code, "upstream_status": exc.upstream_status})
            raise SystemExit(1) from exc
        finally:
            store.close()


if __name__ == "__main__":
    main()
