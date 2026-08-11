import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.ai import LocalDemoAI
from app.long_term_memory import memory_content_allowed
from app.schemas import InferredLongTermMemory, LongTermMemoryInferenceResult
from app.store import Store


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        event = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            if line.startswith("data:"):
                data += line[5:].strip()
        if event and data:
            events.append((event, json.loads(data)))
    return events


class LongTermMemoryApiTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = (Path(self.tempdir.name) / "long-term-memory.db").as_posix()
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

    def login(self, email: str = "long-memory@example.com") -> dict:
        captured = {}
        with patch("app.main.send_registration_code", side_effect=lambda _, code: captured.update(code=code)):
            self.assertEqual(self.client.post("/v1/auth/verification-codes", json={"email": email}).status_code, 204)
        response = self.client.post("/v1/auth/code-login", json={
            "email": email, "verification_code": captured["code"],
        })
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_crud_filters_isolation_forget_and_undo(self):
        self.assertEqual(self.client.get("/v1/long-term-memories").status_code, 401)
        self.login()
        created = self.client.post("/v1/long-term-memories", json={
            "kind": "project", "subject": " Nerva 项目 ", "content": " 我负责 Nerva 的产品设计 ",
        })
        self.assertEqual(created.status_code, 201)
        memory = created.json()
        self.assertEqual(memory["subject"], "Nerva 项目")
        self.assertEqual(memory["status"], "active")
        self.assertEqual(memory["embedding_status"], "ready")
        self.assertEqual(self.client.get("/v1/long-term-memory-events").json()[0]["action"], "remembered")
        self.assertEqual(len(self.client.get("/v1/long-term-memories", params={"kind": "project", "q": "产品"}).json()), 1)
        self.assertEqual(self.client.post("/v1/long-term-memories", json={
            "kind": "project", "subject": "Nerva 项目", "content": "我负责 Nerva 的产品设计",
        }).status_code, 409)
        self.assertEqual(self.client.patch(f"/v1/long-term-memories/{memory['id']}", json={}).status_code, 422)

        deleted = self.client.delete(f"/v1/long-term-memories/{memory['id']}")
        self.assertEqual(deleted.status_code, 200)
        mutation = deleted.json()
        self.assertEqual(self.client.get("/v1/long-term-memories").json(), [])
        restored = self.client.post(f"/v1/long-term-memory-mutations/{mutation['id']}/undo")
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.json()["memory"]["id"], memory["id"])
        self.assertEqual(self.client.get("/v1/long-term-memory-events").json()[0]["action"], "undo")

        self.client.post("/v1/auth/logout")
        self.login("other-memory@example.com")
        self.assertEqual(self.client.patch(f"/v1/long-term-memories/{memory['id']}", json={"content": "越权"}).status_code, 404)
        self.assertEqual(self.client.delete(f"/v1/long-term-memories/{memory['id']}").status_code, 404)

    def test_explicit_memory_is_active_and_recalled_across_chat_sessions(self):
        self.login()
        first = self.client.post("/v1/chat/sessions", json={}).json()
        response = self.client.post(f"/v1/chat/sessions/{first['id']}/messages", json={
            "content": "请记住：我的主项目叫 Nerva",
        })
        events = parse_sse(response.text)
        self.assertIn("long_term_memory_mutation", [name for name, _ in events])
        memories = self.client.get("/v1/long-term-memories").json()
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0]["status"], "active")

        second = self.client.post("/v1/chat/sessions", json={}).json()
        recalled = self.client.post(f"/v1/chat/sessions/{second['id']}/messages", json={
            "content": "我的主项目叫什么？",
        })
        recalled_events = parse_sse(recalled.text)
        context = next(payload for name, payload in recalled_events if name == "memory_context")
        self.assertEqual(context["memories"][0]["id"], memories[0]["id"])
        self.assertNotIn("embedding", context["memories"][0])
        self.assertNotIn("user_id", context["memories"][0])
        done = next(payload for name, payload in recalled_events if name == "done")
        self.assertEqual(done["message"]["memory_refs"], [memories[0]["id"]])
        self.assertEqual(main.store.get_long_term_memory(self.client.get("/v1/auth/me").json()["id"], memories[0]["id"])["use_count"], 1)

    def test_implicit_learning_creates_candidate_and_respects_switches(self):
        class InferenceAI(LocalDemoAI):
            calls = 0

            def infer_long_term_memories(self, **kwargs):
                self.calls += 1
                return LongTermMemoryInferenceResult(memories=[InferredLongTermMemory(
                    action="remember", kind="person", subject="用户角色",
                    content="用户是产品经理", confidence=.9, reason="用户明确陈述职业",
                    target_memory_id=None, explicit=False,
                )])

        user = self.login()
        main.ai = InferenceAI()
        session = self.client.post("/v1/chat/sessions", json={}).json()
        response = self.client.post(f"/v1/chat/sessions/{session['id']}/messages", json={
            "content": "我是产品经理，正在规划 Nerva",
        })
        self.assertIn("long_term_memory_candidates", [name for name, _ in parse_sse(response.text)])
        candidate = main.store.list_long_term_memories(user["id"])[0]
        self.assertEqual(candidate["status"], "candidate")

        main.store.update_knowledge_hub_settings(user["id"], auto_learning_enabled=False)
        session = self.client.post("/v1/chat/sessions", json={}).json()
        self.client.post(f"/v1/chat/sessions/{session['id']}/messages", json={
            "content": "我还负责增长工作",
        })
        self.assertEqual(main.ai.calls, 1)

        main.store.update_knowledge_hub_settings(user["id"], long_term_memory_enabled=False)
        session = self.client.post("/v1/chat/sessions", json={}).json()
        response = self.client.post(f"/v1/chat/sessions/{session['id']}/messages", json={
            "content": "用户角色是什么？",
        })
        self.assertNotIn("memory_context", [name for name, _ in parse_sse(response.text)])

    def test_sensitive_information_filter(self):
        self.assertFalse(memory_content_allowed("API token 是 abc-secret", explicit=True))
        self.assertFalse(memory_content_allowed("我的病历显示高血压", explicit=False))
        self.assertTrue(memory_content_allowed("请记住我的诊断是高血压", explicit=True))


if __name__ == "__main__":
    unittest.main()
