import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.ai import LocalDemoAI
from app.store import Store


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        name = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name and data is not None:
            events.append((name, data))
    return events


class ResearchApiTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = (Path(self.tempdir.name) / "research.db").as_posix()
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

    def test_session_stream_retry_and_user_isolation(self):
        self.assertEqual(self.client.get("/v1/research/sessions").status_code, 401)
        owner = self.login("research-owner@example.com")
        self.assertEqual(self.client.post("/v1/research/sessions", json={"title": "  "}).status_code, 422)
        session = self.client.post("/v1/research/sessions", json={}).json()
        response = self.client.post(f"/v1/research/sessions/{session['id']}/messages", json={
            "content": "什么是混合检索？", "mode": "smart",
        })
        events = parse_sse(response.text)
        self.assertEqual(events[0][0], "start")
        self.assertIn("delta", [name for name, _ in events])
        self.assertEqual(events[-2][0], "sources")
        self.assertEqual(events[-1][0], "done")
        assistant = events[-1][1]["message"]
        self.assertEqual(assistant["basis"], "ai")
        self.assertEqual(assistant["citations"], [])

        web = self.client.post(f"/v1/research/sessions/{session['id']}/messages", json={
            "content": "查询今天的新消息", "mode": "web",
        })
        web_events = parse_sse(web.text)
        self.assertEqual(web_events[-1][0], "error")
        web_assistant_id = web_events[0][1]["assistant_message_id"]
        retried = self.client.post(
            f"/v1/research/messages/{web_assistant_id}/retry", json={"mode": "ai"},
        )
        self.assertEqual(parse_sse(retried.text)[-1][0], "done")
        self.assertEqual(main.store.get_research_message(owner["id"], web_assistant_id)["requested_mode"], "ai")

        self.client.post("/v1/auth/logout")
        self.login("research-other@example.com")
        self.assertEqual(self.client.get(f"/v1/research/sessions/{session['id']}/messages").status_code, 404)
        self.assertEqual(self.client.delete(f"/v1/research/sessions/{session['id']}").status_code, 404)

    def test_web_sources_and_ingestion_are_persistent_and_idempotent(self):
        class WebAI(LocalDemoAI):
            research_model = "web-test"

            def stream_research(self, history, mode):
                yield {"type": "delta", "text": "# 混合检索\n\n混合检索融合关键词和向量结果。"}
                yield {"type": "sources", "basis": "web", "sources": [{
                    "title": "权威资料", "url": "https://example.com/retrieval", "domain": "example.com",
                }]}

        self.login("research-ingestion@example.com")
        main.ai = WebAI()
        session = self.client.post("/v1/research/sessions", json={}).json()
        streamed = self.client.post(f"/v1/research/sessions/{session['id']}/messages", json={
            "content": "研究混合检索", "mode": "web",
        })
        assistant = parse_sse(streamed.text)[-1][1]["message"]
        self.assertEqual(assistant["citations"][0]["url"], "https://example.com/retrieval")
        self.assertEqual(self.client.get("/v1/documents").json(), [])

        first = self.client.post(f"/v1/research/messages/{assistant['id']}/ingestion")
        self.assertEqual(first.status_code, 202)
        second = self.client.post(f"/v1/research/messages/{assistant['id']}/ingestion")
        self.assertEqual(second.status_code, 202)
        self.assertEqual(first.json()["source_id"], second.json()["source_id"])
        processing = self.client.get(f"/v1/sources/{first.json()['source_id']}/processing").json()
        self.assertEqual(processing["status"], "proposed")
        draft = self.client.get(f"/v1/change-sets/{processing['change_set_id']}").json()
        self.assertIn("研究来源", draft["source"]["content"])
        self.assertEqual(self.client.get("/v1/documents").json(), [])
        with patch("app.main.submit_index_rebuild"):
            applied = self.client.post(f"/v1/change-sets/{draft['id']}/apply", json={
                "accepted_item_ids": [item["id"] for item in draft["items"]],
            })
            repeated = self.client.post(f"/v1/change-sets/{draft['id']}/apply", json={
                "accepted_item_ids": [item["id"] for item in draft["items"]],
            })
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(len(self.client.get("/v1/documents").json()), 1)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json()["status"], "applied")
        self.assertEqual(len(self.client.get("/v1/documents").json()), 1)

    def test_generation_conflict_and_startup_recovery(self):
        user = self.login("research-recovery@example.com")
        session = self.client.post("/v1/research/sessions", json={}).json()
        _, assistant = main.store.create_research_turn(
            user["id"], session["id"], "unfinished question", "smart", "demo-model",
        )

        conflict = self.client.post(f"/v1/research/sessions/{session['id']}/messages", json={
            "content": "second question", "mode": "ai",
        })
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(self.client.delete(f"/v1/research/sessions/{session['id']}").status_code, 409)

        self.assertEqual(main.store.fail_interrupted_research_messages(), 1)
        recovered = main.store.get_research_message(user["id"], assistant["id"])
        self.assertEqual(recovered["status"], "failed")
        self.assertEqual(recovered["error_code"], "RESEARCH_INTERRUPTED")

        retried = self.client.post(f"/v1/research/messages/{assistant['id']}/retry")
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(parse_sse(retried.text)[-1][0], "done")
        self.assertEqual(self.client.delete(f"/v1/research/sessions/{session['id']}").status_code, 204)


if __name__ == "__main__":
    unittest.main()
