import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.ai import LocalDemoAI
from app.auth import hash_password, verify_password
from app.settings import settings
from app.store import Store


class AdminPublicApiTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = (Path(self.tempdir.name) / "admin.db").as_posix()
        self.original_store = main.store
        self.original_ai = main.ai
        main.store = Store(f"sqlite+pysqlite:///{db_path}")
        main.ai = LocalDemoAI()
        main.store.ensure_admin(
            username=settings.admin_username,
            email=settings.admin_email,
            password_hash=hash_password(settings.admin_password),
        )
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
            self.assertEqual(self.client.post("/v1/auth/verification-codes", json={"email": email}).status_code, 204)
        return self.client.post("/v1/auth/code-login", json={
            "email": email, "verification_code": captured["code"],
        })

    def admin_login(self, password: str | None = None):
        return self.client.post("/v1/auth/admin-login", json={
            "username": settings.admin_username,
            "password": password or settings.admin_password,
        })

    def test_admin_login_and_role_gate(self):
        wrong = self.admin_login("wrong-password")
        self.assertEqual(wrong.status_code, 401)
        logged_in = self.admin_login()
        self.assertEqual(logged_in.status_code, 200)
        self.assertEqual(logged_in.json()["role"], "admin")
        self.assertEqual(self.client.get("/v1/admin/users").status_code, 200)

        self.client.post("/v1/auth/logout")
        self.assertEqual(self.code_login("reader@example.com").status_code, 200)
        self.assertEqual(self.client.get("/v1/admin/users").status_code, 403)
        self.assertEqual(self.client.get("/v1/admin/knowledge-ownership").status_code, 403)

    def test_public_documents_are_readable_but_admin_only_writable(self):
        self.assertEqual(self.admin_login().status_code, 200)
        created = self.client.post("/v1/admin/public-documents", json={
            "title": "Shared indexing", "markdown": "# Shared indexing\n\nB-tree guidance",
        })
        self.assertEqual(created.status_code, 201)
        document = created.json()
        self.assertEqual(document["visibility"], "public")

        self.client.post("/v1/auth/logout")
        self.assertEqual(self.code_login("reader@example.com").status_code, 200)
        self.assertEqual(self.client.get("/v1/public-documents").json()[0]["id"], document["id"])
        self.assertEqual(self.client.get(f"/v1/public-documents/{document['id']}").status_code, 200)
        self.assertEqual(self.client.put(f"/v1/admin/public-documents/{document['id']}", json={
            "title": "Attack", "markdown": "Attack", "base_version": 1,
        }).status_code, 403)

        included = self.client.get("/v1/search", params={
            "q": "B-tree guidance", "include_public": "true",
        })
        excluded = self.client.get("/v1/search", params={
            "q": "B-tree guidance", "include_public": "false",
        })
        self.assertEqual(included.status_code, 200)
        self.assertTrue(included.json()["items"])
        self.assertEqual(included.json()["items"][0]["visibility"], "public")
        self.assertEqual(excluded.json()["items"], [])

    def test_password_sync_changes_hash_and_revokes_sessions(self):
        self.assertEqual(self.admin_login().status_code, 200)
        admin = main.store.get_user_by_username(settings.admin_username)
        self.assertIsNotNone(admin)
        self.assertTrue(verify_password(settings.admin_password, admin["password_hash"]))
        changed_password = "next-admin-password"
        main.store.ensure_admin(
            username=settings.admin_username, email=settings.admin_email,
            password_hash=hash_password(changed_password), password_matches=False,
        )
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 401)
        self.assertEqual(self.admin_login().status_code, 401)
        self.assertEqual(self.admin_login(changed_password).status_code, 200)

    def test_admin_can_read_private_document_detail_but_regular_user_cannot(self):
        self.assertEqual(self.code_login("private-owner@example.com").status_code, 200)
        draft_response = self.client.post("/v1/ingestions", json={
            "kind": "text", "title": "Private operations", "content": "Only the owner and administrator may read this.",
        })
        self.assertEqual(draft_response.status_code, 201)
        draft = draft_response.json()
        applied = self.client.post(f"/v1/change-sets/{draft['id']}/apply", json={
            "accepted_item_ids": [item["id"] for item in draft["items"]],
        })
        self.assertEqual(applied.status_code, 200)
        private_document = self.client.get("/v1/documents").json()[0]
        self.assertEqual(
            self.client.get(f"/v1/admin/documents/{private_document['id']}").status_code,
            403,
        )

        self.client.post("/v1/auth/logout")
        self.assertEqual(self.admin_login().status_code, 200)
        detail = self.client.get(f"/v1/admin/documents/{private_document['id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["id"], private_document["id"])
        self.assertEqual(detail.json()["visibility"], "private")
        self.assertTrue(detail.json()["markdown"])


if __name__ == "__main__":
    unittest.main()
