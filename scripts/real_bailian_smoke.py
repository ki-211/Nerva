"""Run a small real two-stage Bailian call without printing source or credentials."""

import tempfile
from pathlib import Path

from apps.api.app.ai import AIProviderError, BailianAI, retrieve_candidates
from apps.api.app.logging_config import configure_logging
from apps.api.app.prompts import EXTRACT_PROMPT_VERSION, MERGE_PROMPT_VERSION
from apps.api.app.store import Store


def main() -> None:
    configure_logging()
    ai = BailianAI()
    content = "Nerva 是一个个人知识系统。新输入必须先生成可审批的变更草案，批准后才修改正式文档。"
    title = "Nerva 审批原则"
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
                "provider": ai.provider, "model": ai.model,
                "units": len(extraction.units), "changes": len(proposals),
                "operations": [item.operation for item in proposals],
                "draft_status": draft["status"], "applied_status": applied["status"],
                "documents": len(store.list_documents(user["id"])),
                "events": len(store.list_events(user["id"])),
            })
        except AIProviderError as exc:
            response = getattr(exc.__cause__, "response", None)
            upstream = None
            if response is not None:
                try:
                    upstream_error = response.json().get("error", {})
                    upstream = {
                        "code": upstream_error.get("code"),
                        "message": upstream_error.get("message"),
                        "param": upstream_error.get("param"),
                    }
                except ValueError:
                    upstream = {"code": "non-json-error"}
            print({"error": exc.code, "upstream": upstream})
            raise SystemExit(1) from exc
        finally:
            store.close()


if __name__ == "__main__":
    main()
