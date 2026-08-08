import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.ai import AIProviderError, LocalDemoAI
from app.store import Store


class AuthApiTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = (Path(self.tempdir.name) / "auth.db").as_posix()
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

    def code_login(self, email: str):
        captured = {}
        with patch("app.main.send_registration_code", side_effect=lambda target, code: captured.update(code=code)):
            sent = self.client.post("/v1/auth/verification-codes", json={"email": email})
        self.assertEqual(sent.status_code, 204)
        return self.client.post("/v1/auth/code-login", json={
            "email": email, "verification_code": captured["code"],
        })

    def test_first_code_login_creates_user_and_next_login_reuses_it(self):
        response = self.code_login("Owner@Example.com")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "owner@example.com")
        user_id = response.json()["id"]
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 200)

        self.assertEqual(self.client.post("/v1/auth/logout").status_code, 204)
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 401)
        again = self.code_login("owner@example.com")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["id"], user_id)

    def test_invalid_code_and_send_cooldown(self):
        invalid = self.client.post("/v1/auth/code-login", json={
            "email": "new@example.com", "verification_code": "123456",
        })
        self.assertEqual(invalid.status_code, 400)
        with patch("app.main.send_registration_code"):
            first_send = self.client.post("/v1/auth/verification-codes", json={"email": "cooldown@example.com"})
            second_send = self.client.post("/v1/auth/verification-codes", json={"email": "cooldown@example.com"})
        self.assertEqual(first_send.status_code, 204)
        self.assertEqual(second_send.status_code, 429)

    def test_untrusted_origin_is_rejected(self):
        response = self.client.post(
            "/v1/auth/code-login",
            headers={"Origin": "https://evil.example"},
            json={"email": "nobody@example.com", "verification_code": "123456"},
        )
        self.assertEqual(response.status_code, 403)

    def test_auth_required_and_cross_user_isolation(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/v1/documents").status_code, 401)

        self.assertEqual(self.code_login("a@example.com").status_code, 200)
        draft = self.client.post("/v1/ingestions", json={"kind": "text", "title": "Private", "content": "A private note"})
        self.assertEqual(draft.status_code, 201)
        draft_id = draft.json()["id"]
        self.assertEqual(self.client.post(f"/v1/change-sets/{draft_id}/apply", json={"accepted_item_ids": None}).status_code, 200)
        self.client.post("/v1/auth/logout")

        self.assertEqual(self.code_login("b@example.com").status_code, 200)
        self.assertEqual(self.client.get("/v1/documents").json(), [])
        self.assertEqual(self.client.get("/v1/knowledge-events").json(), [])
        self.assertEqual(self.client.get(f"/v1/change-sets/{draft_id}").status_code, 404)
        self.assertEqual(self.client.post(f"/v1/change-sets/{draft_id}/apply", json={"accepted_item_ids": None}).status_code, 404)

    def test_failed_source_can_retry_and_is_user_scoped(self):
        class FailingAI:
            provider = "test"
            model = "timeout-model"

            def extract_inputs(self, inputs, source_label, **kwargs):
                raise AIProviderError("AI_TIMEOUT", "Model timed out", retryable=True, status_code=503)

            def plan_units(self, units, candidates, source_label, **kwargs):
                raise AssertionError("plan should not run")

        self.assertEqual(self.code_login("retry-a@example.com").status_code, 200)
        main.ai = FailingAI()
        failed = self.client.post("/v1/ingestions", json={"content": "Retry this knowledge"})
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.json()["detail"]["code"], "AI_TIMEOUT")
        source_id = failed.json()["detail"]["source_id"]

        self.client.post("/v1/auth/logout")
        self.assertEqual(self.code_login("retry-b@example.com").status_code, 200)
        self.assertEqual(self.client.post(f"/v1/sources/{source_id}/retry").status_code, 404)

        self.client.post("/v1/auth/logout")
        self.assertEqual(self.code_login("retry-a@example.com").status_code, 200)
        main.ai = LocalDemoAI()
        retried = self.client.post(f"/v1/sources/{source_id}/retry")
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(len(retried.json()["items"]), 1)

    def test_document_read_history_edit_conflict_and_user_isolation(self):
        self.assertEqual(self.code_login("editor@example.com").status_code, 200)
        draft = self.client.post("/v1/ingestions", json={
            "title": "Editable", "content": "Initial knowledge",
        }).json()
        self.assertEqual(self.client.post(
            f"/v1/change-sets/{draft['id']}/apply", json={"accepted_item_ids": None},
        ).status_code, 200)
        document = self.client.get("/v1/documents").json()[0]
        document_id = document["id"]

        saved = self.client.put(f"/v1/documents/{document_id}", json={
            "title": "Edited", "markdown": "# Edited\n\nHuman text",
            "base_version": 1, "reason": "manual clarification",
        })
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["version"], 2)
        history = self.client.get(f"/v1/documents/{document_id}/versions")
        self.assertEqual([item["version"] for item in history.json()], [2, 1])

        event = self.client.get("/v1/knowledge-events").json()[0]
        self.assertEqual(event["origin"], "manual_edit")
        detail = self.client.get(f"/v1/change-sets/{event['change_set_id']}").json()
        self.assertEqual(detail["items"][0]["operation"], "UPDATE_DOCUMENT")
        self.assertIsNone(detail["source"])

        conflict = self.client.put(f"/v1/documents/{document_id}", json={
            "title": "Stale", "markdown": "Stale", "base_version": 1,
        })
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["detail"]["code"], "DOCUMENT_VERSION_CONFLICT")
        self.assertEqual(conflict.json()["detail"]["current_version"], 2)
        self.assertEqual(self.client.put(f"/v1/documents/{document_id}", json={
            "title": " ", "markdown": " ", "base_version": 2,
        }).status_code, 422)

        self.client.post("/v1/auth/logout")
        self.assertEqual(self.code_login("reader@example.com").status_code, 200)
        self.assertEqual(self.client.get(f"/v1/documents/{document_id}").status_code, 404)
        self.assertEqual(self.client.get(f"/v1/documents/{document_id}/versions").status_code, 404)
        self.assertEqual(self.client.put(f"/v1/documents/{document_id}", json={
            "title": "Attack", "markdown": "Attack", "base_version": 2,
        }).status_code, 404)

    def test_upstream_details_are_logged_but_not_returned(self):
        class FailingAI:
            provider = "bailian"
            model = "qwen3.6-flash"

            def extract_inputs(self, inputs, source_label, **kwargs):
                raise AIProviderError(
                    "AI_UPSTREAM_ERROR",
                    "模型服务暂时不可用",
                    retryable=False,
                    status_code=502,
                    upstream_status=400,
                    upstream_code="InvalidParameter",
                    upstream_message="Json mode response is not supported when thinking is enabled",
                    request_id="req-123",
                )

            def plan_units(self, units, candidates, source_label, **kwargs):
                raise AssertionError("plan should not run")

        self.assertEqual(self.code_login("logging@example.com").status_code, 200)
        main.ai = FailingAI()
        with self.assertLogs("nerva.api", level="WARNING") as captured:
            response = self.client.post("/v1/ingestions", json={"content": "Trigger logging"})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"]["message"], "模型服务暂时不可用")
        self.assertNotIn("upstream_status", response.text)
        log_output = "\n".join(captured.output)
        self.assertIn("upstream_status=400", log_output)
        self.assertIn("upstream_code=InvalidParameter", log_output)
        self.assertIn("request_id=req-123", log_output)
        self.assertIn("upstream_message='Json mode response is not supported when thinking is enabled'", log_output)


if __name__ == "__main__":
    unittest.main()
