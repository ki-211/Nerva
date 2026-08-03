import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.store import Store


class AuthApiTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = (Path(self.tempdir.name) / "auth.db").as_posix()
        self.original_store = main.store
        main.store = Store(f"sqlite+pysqlite:///{db_path}")
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        main.store.close()
        main.store = self.original_store
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


if __name__ == "__main__":
    unittest.main()
