"""Exercise synthetic merge, conflict and memory behavior with the real Bailian model."""

import logging
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.api.app import main as api_main
from apps.api.app.ai import AIProviderError, BailianAI
from apps.api.app.memories import load_active_memories
from apps.api.app.store import Store


def process_text(store: Store, user_id: str, title: str, content: str) -> dict:
    source = store.create_source(user_id, "text", content, title)
    draft = api_main.process_source(user_id, source["id"])
    if draft is None:
        raise RuntimeError("Synthetic source was not claimed")
    return {"source": source, "draft": draft}


def operations(draft: dict) -> list[str]:
    return [item["operation"] for item in draft["items"]]


def main() -> None:
    if os.getenv("NERVA_RUN_REAL_BAILIAN_SMOKE") != "1":
        raise SystemExit("Set NERVA_RUN_REAL_BAILIAN_SMOKE=1 to run the real Bailian smoke")
    logging.disable(logging.CRITICAL)

    with tempfile.TemporaryDirectory(prefix="nerva-memory-smoke-") as tempdir:
        isolated = Store(f"sqlite+pysqlite:///{(Path(tempdir) / 'memory.db').as_posix()}")
        previous_store, previous_ai = api_main.store, api_main.ai
        ai = BailianAI()
        try:
            api_main.store, api_main.ai = isolated, ai
            user = isolated.create_user("memory-smoke@nerva.invalid", "Memory Smoke")

            first = process_text(
                isolated, user["id"], "合成 Orion 基线",
                "合成系统 Orion 的生产服务固定监听 8443 端口，并通过 TLS 接收请求。",
            )
            docs_before_approval = len(isolated.list_documents(user["id"]))
            first_applied = isolated.apply_change_set(user["id"], first["draft"]["id"], None)

            merged = process_text(
                isolated, user["id"], "合成 Orion 补充",
                "合成系统 Orion 的健康检查路径是 /healthz，属于同一份生产部署规范。",
            )
            merge_detected = "ADD_BLOCK" in operations(merged["draft"])
            merged_applied = isolated.apply_change_set(user["id"], merged["draft"]["id"], None)

            conflict = process_text(
                isolated, user["id"], "合成 Orion 冲突",
                "两份同等级合成来源互相矛盾：一份声明 Orion 生产端口为 8443，另一份声明为 9443，现有证据无法判定哪份有效。",
            )
            conflict_detected = "REPORT_CONFLICT" in operations(conflict["draft"])

            naming = isolated.create_memory(
                user["id"], kind="naming", content="所有新文档标题必须以 NERVA- 开头",
                scope="global", scope_ref=None, status="active",
                confidence=1.0, origin="user_explicit",
            )
            named = process_text(
                isolated, user["id"], "合成 Vega 协议",
                "合成协议 Vega 使用蓝色信封传递校验码，保留期固定为七天。",
            )
            preferred_titles = [
                item["target_title"] for item in named["draft"]["items"]
                if item["operation"] == "CREATE_DOCUMENT"
            ]
            naming_observed = bool(preferred_titles) and all(
                title.startswith("NERVA-") for title in preferred_titles
            )

            queued = isolated.queue_source_reprocess(
                user["id"], named["source"]["id"], named["draft"]["id"],
                "这是我长期稳定的全局写作偏好，不是本次临时要求：从现在起，以后的每一篇文档都必须使用简洁短句，并始终保留 API 等英文术语。请以后都这样处理。",
            )
            if not queued:
                raise RuntimeError("Synthetic re-analysis was not queued")
            reprocessed = api_main.process_source(user["id"], named["source"]["id"])
            candidates = isolated.list_memories(user["id"], status="candidate")
            candidate_inactive = all(
                item["id"] not in {memory["id"] for memory in load_active_memories(isolated, user["id"])}
                for item in candidates
            )
            for candidate in candidates:
                isolated.update_memory(user["id"], candidate["id"], status="active")
            approved_active = all(
                item["id"] in {memory["id"] for memory in load_active_memories(isolated, user["id"])}
                for item in candidates
            )

            follow_up = process_text(
                isolated, user["id"], "合成 Lyra 接口",
                "合成服务 Lyra 暴露 Query API；请求失败时返回可重试状态。",
            )
            approved_used = bool(candidates) and all(
                isolated.get_memory(user["id"], item["id"])["use_count"] == 1
                for item in candidates
            )
            naming_used = isolated.get_memory(user["id"], naming["id"])["use_count"] >= 2

            result = {
                "model": ai.model,
                "create_operations": operations(first["draft"]),
                "merge_operations": operations(merged["draft"]),
                "conflict_operations": operations(conflict["draft"]),
                "reanalysis_operations": operations(reprocessed),
                "follow_up_operations": operations(follow_up["draft"]),
                "first_status": first_applied["status"],
                "merged_status": merged_applied["status"],
                "draft_preserved_documents": docs_before_approval == 0,
                "merge_detected": merge_detected,
                "conflict_detected": conflict_detected,
                "naming_observed": naming_observed,
                "candidate_count": len(candidates),
                "candidate_inactive_before_approval": candidate_inactive,
                "candidate_active_after_approval": approved_active,
                "approved_memory_used": approved_used,
                "naming_memory_used": naming_used,
            }
            print(result)
            required = [
                result["draft_preserved_documents"], result["merge_detected"],
                result["conflict_detected"], result["naming_observed"],
                result["candidate_count"] > 0, result["candidate_inactive_before_approval"],
                result["candidate_active_after_approval"], result["approved_memory_used"],
                result["naming_memory_used"],
            ]
            if not all(required):
                raise SystemExit(1)
        except AIProviderError as exc:
            print({"error": exc.code, "upstream_status": exc.upstream_status})
            raise SystemExit(1) from exc
        finally:
            api_main.store, api_main.ai = previous_store, previous_ai
            isolated.close()


if __name__ == "__main__":
    main()
