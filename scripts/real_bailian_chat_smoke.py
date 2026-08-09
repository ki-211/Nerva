"""Run a synthetic knowledge-chat flow against the real Bailian model."""

import json
import logging
import os
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.api.app import main as api_main
from apps.api.app.ai import AIProviderError, BailianAI, MergeProposal
from apps.api.app.store import Store


def parse_events(chunks) -> list[tuple[str, dict]]:
    events = []
    for chunk in chunks:
        event_name = None
        data = None
        for line in chunk.strip().splitlines():
            if line.startswith("event: "):
                event_name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if event_name and data is not None:
            events.append((event_name, data))
    return events


def run_turn(store: Store, user_id: str, session_id: str, content: str, model: str):
    turn = store.create_chat_turn(user_id, session_id, content, model)
    if turn is None:
        raise RuntimeError("Synthetic chat session was not found")
    return parse_events(api_main._chat_stream(user_id, *turn))


def main() -> None:
    if os.getenv("NERVA_RUN_REAL_BAILIAN_SMOKE") != "1":
        raise SystemExit("Set NERVA_RUN_REAL_BAILIAN_SMOKE=1 to run the real Bailian smoke")
    logging.disable(logging.CRITICAL)

    with tempfile.TemporaryDirectory(prefix="nerva-chat-smoke-") as tempdir:
        isolated = Store(f"sqlite+pysqlite:///{(Path(tempdir) / 'chat.db').as_posix()}")
        previous_store, previous_ai = api_main.store, api_main.ai
        ai = BailianAI()
        try:
            api_main.store, api_main.ai = isolated, ai
            user = isolated.create_user("chat-smoke@nerva.invalid", "Chat Smoke")

            proposal = MergeProposal(
                operation="CREATE_DOCUMENT",
                unit_refs=["synthetic-unit-1"],
                target_document_id=None,
                target_title="Orion 合成服务说明",
                reason="将合成事实建立为正式文档",
                before=None,
                after=(
                    "# Orion 合成服务说明\n\n"
                    "Orion 是仅用于自动化验收的合成服务。它使用蓝色信封传递校验码，"
                    "校验码保留七天。"
                ),
                evidence="本条内容完全由测试程序合成。",
                confidence=1.0,
            )
            draft = isolated.create_change_set(
                user["id"], "text", "合成 Orion 验收资料", "Orion 合成服务说明", proposal,
            )
            applied = isolated.apply_change_set(user["id"], draft["id"], None)
            if not applied or applied["status"] != "applied":
                raise RuntimeError("Synthetic document was not approved")

            style = isolated.create_memory(
                user["id"], kind="style", content="回答应简洁，并保留 API 等英文术语。",
                scope="global", scope_ref=None, status="active", confidence=1.0,
                origin="user_explicit",
            )
            session = isolated.create_chat_session(user["id"], "合成知识问答")
            knowledge_events = run_turn(
                isolated, user["id"], session["id"],
                "Orion 使用什么方式传递校验码，保留多久？", ai.model,
            )
            preference_events = run_turn(
                isolated, user["id"], session["id"],
                "请记住：以后回答都使用简洁短句，并保留 API 英文术语。", ai.model,
            )

            event_names = [name for name, _ in knowledge_events]
            done_payloads = [payload for name, payload in knowledge_events if name == "done"]
            memory_payloads = [
                payload for name, payload in preference_events if name == "memory_candidates"
            ]
            done = done_payloads[-1]["message"] if done_payloads else {}
            candidates = [
                memory for payload in memory_payloads for memory in payload.get("memories", [])
            ]
            style_after = isolated.get_memory(user["id"], style["id"])
            result = {
                "model": ai.model,
                "start_count": event_names.count("start"),
                "delta_count": event_names.count("delta"),
                "done_count": event_names.count("done"),
                "assistant_status": done.get("status"),
                "grounding": done.get("grounding"),
                "citation_count": len(done.get("citations", [])),
                "candidate_count": len(candidates),
                "memory_used": bool(style_after and style_after["use_count"] >= 2),
                "synthetic_only": True,
            }
            print(result)
            required = [
                result["start_count"] == 1,
                result["delta_count"] > 0,
                result["done_count"] == 1,
                result["assistant_status"] == "completed",
                result["grounding"] in {"knowledge", "knowledge_plus_general"},
                result["citation_count"] > 0,
                result["candidate_count"] > 0,
                result["memory_used"],
                result["synthetic_only"],
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
