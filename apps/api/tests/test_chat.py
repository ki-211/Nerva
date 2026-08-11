import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.ai import AIProviderError, LocalDemoAI
from app.chat import ChatStreamParser, build_retrieval_query, retrieve_chat_sources, should_infer_memory
from app.schemas import InferredMemory, MemoryInferenceResult
from app.store import Store


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        event = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if event and data is not None:
            events.append((event, data))
    return events


class ChatApiTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = (Path(self.tempdir.name) / "chat.db").as_posix()
        self.original_store = main.store
        self.original_ai = main.ai
        main.store = Store(f"sqlite+pysqlite:///{db_path}")
        main.ai = LocalDemoAI()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        main.store.close()
        main.store = self.original_store
        main.ai = self.original_ai
        self.tempdir.cleanup()

    def login(self, email: str) -> dict:
        captured = {}
        with patch("app.main.send_registration_code", side_effect=lambda target, code: captured.update(code=code)):
            self.assertEqual(self.client.post(
                "/v1/auth/verification-codes", json={"email": email},
            ).status_code, 204)
        response = self.client.post("/v1/auth/code-login", json={
            "email": email, "verification_code": captured["code"],
        })
        self.assertEqual(response.status_code, 200)
        return response.json()

    def create_document(self) -> dict:
        draft_response = self.client.post("/v1/ingestions", json={
            "kind": "text", "title": "Orion 部署", "content": "Orion 服务使用 8443 端口提供 TLS 接口。",
        })
        self.assertEqual(draft_response.status_code, 201)
        draft = draft_response.json()
        applied = self.client.post(f"/v1/change-sets/{draft['id']}/apply", json={
            "accepted_item_ids": [item["id"] for item in draft["items"]],
        })
        self.assertEqual(applied.status_code, 200)
        return self.client.get("/v1/documents").json()[0]

    def test_session_crud_validation_and_user_isolation(self):
        self.assertEqual(self.client.get("/v1/chat/sessions").status_code, 401)
        self.login("chat-owner@example.com")
        self.assertEqual(self.client.post("/v1/chat/sessions", json={"title": "  "}).status_code, 422)
        created = self.client.post("/v1/chat/sessions", json={}).json()
        self.assertEqual(created["title"], "新对话")
        renamed = self.client.patch(f"/v1/chat/sessions/{created['id']}", json={"title": "部署问答"})
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["title"], "部署问答")

        self.client.post("/v1/auth/logout")
        self.login("chat-other@example.com")
        self.assertEqual(self.client.get(f"/v1/chat/sessions/{created['id']}/messages").status_code, 404)
        self.assertEqual(self.client.patch(f"/v1/chat/sessions/{created['id']}", json={"title": "x"}).status_code, 404)
        self.assertEqual(self.client.delete(f"/v1/chat/sessions/{created['id']}").status_code, 404)

    def test_stream_uses_documents_memories_and_persists_citations(self):
        user = self.login("chat-stream@example.com")
        document = self.create_document()
        style = main.store.create_memory(
            user["id"], kind="style", content="使用简洁回答", scope="global", scope_ref=None,
            status="active", confidence=1.0, origin="user_explicit",
        )
        candidate = main.store.create_memory(
            user["id"], kind="domain", content="候选背景", scope="global", scope_ref=None,
            status="candidate", confidence=0.8, origin="ai_inferred",
        )
        session = self.client.post("/v1/chat/sessions", json={}).json()
        with self.assertLogs("nerva.api", level="INFO") as captured_logs:
            response = self.client.post(f"/v1/chat/sessions/{session['id']}/messages", json={
                "content": "Orion 使用什么端口？",
            })
        self.assertEqual(response.status_code, 200)
        log_output = "\n".join(captured_logs.output)
        self.assertIn("chat_generation_started", log_output)
        self.assertIn("chat_context_prepared", log_output)
        self.assertIn("chat_first_delta", log_output)
        self.assertIn("chat_generation_completed", log_output)
        events = parse_sse(response.text)
        self.assertEqual(events[0][0], "start")
        self.assertIn("delta", [name for name, _ in events])
        self.assertEqual(events[-1][0], "done")
        assistant = events[-1][1]["message"]
        self.assertEqual(assistant["status"], "completed")
        self.assertEqual(assistant["grounding"], "knowledge")
        self.assertEqual(assistant["citations"][0]["document_id"], document["id"])
        history = self.client.get(f"/v1/chat/sessions/{session['id']}/messages").json()
        self.assertEqual([item["role"] for item in history], ["user", "assistant"])
        self.assertEqual(main.store.get_memory(user["id"], style["id"])["use_count"], 1)
        self.assertEqual(main.store.get_memory(user["id"], candidate["id"])["use_count"], 0)
        self.assertNotEqual(self.client.get("/v1/chat/sessions").json()[0]["title"], "新对话")

    def test_knowledge_hub_settings_disable_chat_personalization_and_learning(self):
        class MemoryAI(LocalDemoAI):
            def __init__(self):
                self.memory_blocks = []
                self.inference_calls = 0

            def stream_chat(self, history, sources, **kwargs):
                self.memory_blocks.append(kwargs.get("memory_block", ""))
                yield from super().stream_chat(history, sources, **kwargs)

            def infer_preferences(self, **kwargs):
                self.inference_calls += 1
                return MemoryInferenceResult(memories=[InferredMemory(
                    kind="style", content="保留 API 英文", confidence=0.9, reason="explicit",
                )])

        user = self.login("chat-hub-settings@example.com")
        style = main.store.create_memory(
            user["id"], kind="style", content="使用简洁回答", scope="global", scope_ref=None,
            status="active", confidence=1.0, origin="user_explicit",
        )
        main.store.update_knowledge_hub_settings(
            user["id"], personalization_enabled=False, auto_learning_enabled=False,
        )
        main.ai = MemoryAI()
        session = self.client.post("/v1/chat/sessions", json={}).json()
        response = self.client.post(f"/v1/chat/sessions/{session['id']}/messages", json={
            "content": "请记住：以后回答都保留 API 英文。",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(main.ai.memory_blocks, [""])
        self.assertEqual(main.ai.inference_calls, 0)
        self.assertNotIn("memory_candidates", [name for name, _ in parse_sse(response.text)])
        self.assertEqual(main.store.get_memory(user["id"], style["id"])["use_count"], 0)

    def test_explicit_preference_creates_candidate_but_project_fact_does_not(self):
        class MemoryAI(LocalDemoAI):
            def infer_preferences(self, **kwargs):
                return MemoryInferenceResult(memories=[InferredMemory(
                    kind="style", content="保留 API 英文", confidence=0.9, reason="explicit",
                )])

        self.login("chat-memory@example.com")
        main.ai = MemoryAI()
        session = self.client.post("/v1/chat/sessions", json={}).json()
        response = self.client.post(f"/v1/chat/sessions/{session['id']}/messages", json={
            "content": "请记住：以后回答都保留 API 英文。",
        })
        events = parse_sse(response.text)
        memory_events = [data for name, data in events if name == "memory_candidates"]
        self.assertEqual(len(memory_events[0]["memories"]), 1)

        second = self.client.post("/v1/chat/sessions", json={}).json()
        fact = self.client.post(f"/v1/chat/sessions/{second['id']}/messages", json={
            "content": "请记住 Orion 端口是 8443。",
        })
        self.assertNotIn("memory_candidates", [name for name, _ in parse_sse(fact.text)])
        self.assertEqual(len(main.store.list_memories(self.client.get("/v1/auth/me").json()["id"])), 1)

    def test_failure_busy_delete_cancel_and_retry(self):
        class FailingAI(LocalDemoAI):
            model = "failing-chat"

            def stream_chat(self, *args, **kwargs):
                raise AIProviderError("AI_TIMEOUT", "模型响应超时", retryable=True)
                yield ""

        user = self.login("chat-retry@example.com")
        session = self.client.post("/v1/chat/sessions", json={}).json()
        main.ai = FailingAI()
        failed = self.client.post(f"/v1/chat/sessions/{session['id']}/messages", json={"content": "hello"})
        events = parse_sse(failed.text)
        self.assertEqual(events[-1][0], "error")
        assistant_id = events[0][1]["assistant_message_id"]
        self.assertEqual(main.store.get_chat_message(user["id"], assistant_id)["status"], "failed")

        main.ai = LocalDemoAI()
        retried = self.client.post(f"/v1/chat/messages/{assistant_id}/retry")
        self.assertEqual(parse_sse(retried.text)[-1][0], "done")
        self.assertEqual(main.store.get_chat_message(user["id"], assistant_id)["status"], "completed")

        turn = main.store.create_chat_turn(user["id"], session["id"], "busy", main.ai.model)
        self.assertIsNotNone(turn)
        busy = self.client.post(f"/v1/chat/sessions/{session['id']}/messages", json={"content": "again"})
        self.assertEqual(busy.status_code, 409)
        self.assertEqual(self.client.delete(f"/v1/chat/sessions/{session['id']}").status_code, 409)
        main.store.fail_chat_message(user["id"], turn[1]["id"], "CHAT_CANCELLED", cancelled=True)
        self.assertEqual(self.client.delete(f"/v1/chat/sessions/{session['id']}").status_code, 204)


class ChatUtilityTest(unittest.TestCase):
    def test_context_retrieval_parser_and_memory_trigger(self):
        query = build_retrieval_query([
            {"role": "user", "content": f"q{index}"} for index in range(6)
        ])
        self.assertNotIn("q1", query)
        self.assertIn("q5", query)
        sources = retrieve_chat_sources("Orion 端口", [
            {"id": "doc_a", "title": "Orion", "markdown": "# Orion\n\n端口为 8443。"},
            {"id": "doc_b", "title": "Other", "markdown": "unrelated"},
        ])
        self.assertEqual([item["document_id"] for item in sources], ["doc_a"])
        parser = ChatStreamParser(True)
        self.assertEqual(parser.feed("GROUNDING: know"), [])
        self.assertEqual(parser.feed("ledge\n答案 [S1]"), ["答案 [S1]"])
        self.assertEqual(parser.answer, "答案 [S1]")
        self.assertTrue(should_infer_memory("请记住以后使用短句"))
        self.assertFalse(should_infer_memory("请记住端口是 8443"))


if __name__ == "__main__":
    unittest.main()
