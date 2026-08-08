import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.ai import LocalDemoAI
from app.exports import HUMAN_SCHEMA_VERSION, MACHINE_SCHEMA_VERSION
from app.store import Store


class ExportApiTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = (Path(self.tempdir.name) / "exports.db").as_posix()
        self.original_store = main.store
        self.original_ai = main.ai
        main.store = Store(f"sqlite+pysqlite:///{db_path}")
        main.ai = LocalDemoAI()
        self.client = TestClient(main.app)
        self.user_id = self.code_login("exporter@example.com").json()["id"]

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

    def create_document(self, title: str, content: str) -> dict:
        proposal = main.ai.propose(content, title, [])
        draft = main.store.create_change_set(self.user_id, "text", content, title, proposal)
        applied = main.store.apply_change_set(self.user_id, draft["id"], None)
        document_id = applied["items"][0]["target_document_id"]
        return main.store.get_document(self.user_id, document_id)

    @staticmethod
    def open_zip(response):
        return zipfile.ZipFile(io.BytesIO(response.content))

    @staticmethod
    def read_jsonl(archive: zipfile.ZipFile, name: str) -> list[dict]:
        content = archive.read(name).decode("utf-8")
        return [json.loads(line) for line in content.splitlines() if line]

    def test_single_markdown_latest_history_validation_and_isolation(self):
        document = self.create_document("知识/问答:*?", "# 第一版\n\n原始内容")
        main.store.update_document(
            self.user_id, document["id"], title="知识/问答:*?",
            markdown="# 第二版\n\n人工修改", base_version=1, reason="更新正文",
        )

        latest = self.client.get("/v1/exports/markdown", params={
            "scope": "document", "document_id": document["id"],
        })
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.headers["content-type"], "text/markdown; charset=utf-8")
        self.assertIn("filename*=UTF-8''", latest.headers["content-disposition"])
        self.assertIn("人工修改", latest.text)

        historical = self.client.get("/v1/exports/markdown", params={
            "scope": "document", "document_id": document["id"], "version": 1,
        })
        self.assertEqual(historical.status_code, 200)
        self.assertIn("原始内容", historical.text)
        self.assertNotIn("人工修改", historical.text)
        self.assertEqual(self.client.get("/v1/exports/markdown", params={
            "scope": "document",
        }).status_code, 422)
        self.assertEqual(self.client.get("/v1/exports/markdown", params={
            "scope": "library", "document_id": document["id"],
        }).status_code, 422)
        self.assertEqual(self.client.get("/v1/exports/markdown", params={
            "scope": "document", "document_id": document["id"], "version": 99,
        }).status_code, 404)

        self.client.post("/v1/auth/logout")
        self.user_id = self.code_login("other-exporter@example.com").json()["id"]
        self.assertEqual(self.client.get("/v1/exports/markdown", params={
            "scope": "document", "document_id": document["id"],
        }).status_code, 404)
        self.assertEqual(self.client.get("/v1/exports/knowledge-package", params={
            "scope": "document", "document_id": document["id"],
        }).status_code, 404)

    def test_library_markdown_zip_handles_empty_unicode_and_duplicate_titles(self):
        empty = self.client.get("/v1/exports/markdown", params={"scope": "library"})
        self.assertEqual(empty.status_code, 200)
        with self.open_zip(empty) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["schema_version"], HUMAN_SCHEMA_VERSION)
            self.assertEqual(manifest["counts"]["documents"], 0)
            self.assertEqual(
                archive.read("index.md").decode("utf-8"),
                "# Nerva 知识库\n\n知识库当前为空。\n",
            )

        empty_ai = self.client.get("/v1/exports/knowledge-package", params={"scope": "library"})
        self.assertEqual(empty_ai.status_code, 200)
        with self.open_zip(empty_ai) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["schema_version"], MACHINE_SCHEMA_VERSION)
            self.assertTrue(all(count == 0 for count in manifest["counts"].values()))
            for name in (
                "documents", "document_versions", "sources", "knowledge_units",
                "change_sets", "change_items", "knowledge_events",
            ):
                self.assertEqual(self.read_jsonl(archive, f"{name}.jsonl"), [])

        first = self.create_document("../相同/[标题]?", "第一篇唯一内容")
        second = self.create_document("../相同/[标题]?", "第二篇唯一内容")
        self.assertNotEqual(first["id"], second["id"])
        response = self.client.get("/v1/exports/markdown", params={"scope": "library"})
        self.assertEqual(response.status_code, 200)
        with self.open_zip(response) as archive:
            markdown_names = [name for name in archive.namelist() if name.startswith("markdown/")]
            self.assertEqual(len(markdown_names), 2)
            self.assertEqual(len(set(markdown_names)), 2)
            combined = "\n".join(archive.read(name).decode("utf-8") for name in markdown_names)
            self.assertIn("第一篇唯一内容", combined)
            self.assertIn("第二篇唯一内容", combined)
            self.assertFalse(any(".." in name or "\\" in name for name in archive.namelist()))

    def test_ai_package_full_and_single_lineage_exclude_sensitive_and_other_document_content(self):
        first = self.create_document("First", "FIRST_PRIVATE_KNOWLEDGE")
        second = self.create_document("Second", "SECOND_MUST_NOT_LEAK")
        main.store.update_document(
            self.user_id, first["id"], title="First Renamed",
            markdown="# First Renamed\n\nFIRST_EDITED", base_version=1, reason="manual history",
        )

        single = self.client.get("/v1/exports/knowledge-package", params={
            "scope": "document", "document_id": first["id"],
        })
        self.assertEqual(single.status_code, 200)
        self.assertEqual(single.headers["content-type"], "application/zip")
        with self.open_zip(single) as archive:
            expected = {
                "manifest.json", "README.md", "documents.jsonl", "document_versions.jsonl",
                "sources.jsonl", "knowledge_units.jsonl", "change_sets.jsonl",
                "change_items.jsonl", "knowledge_events.jsonl",
            }
            self.assertTrue(expected.issubset(set(archive.namelist())))
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["schema_version"], MACHINE_SCHEMA_VERSION)
            self.assertEqual(manifest["scope"], "document")
            self.assertFalse(manifest["privacy"]["contains_sessions"])
            documents = self.read_jsonl(archive, "documents.jsonl")
            versions = self.read_jsonl(archive, "document_versions.jsonl")
            changes = self.read_jsonl(archive, "change_items.jsonl")
            self.assertEqual([item["id"] for item in documents], [first["id"]])
            self.assertEqual([item["version"] for item in versions], [1, 2])
            self.assertTrue(changes)
            self.assertTrue(all(item["target_document_id"] == first["id"] for item in changes))
            all_text = "\n".join(archive.read(name).decode("utf-8") for name in archive.namelist())
            for forbidden in ('"user_id"', '"error_message"', 'token_hash', 'verification_code', 'SECOND_MUST_NOT_LEAK'):
                self.assertNotIn(forbidden, all_text)

        full = self.client.get("/v1/exports/knowledge-package", params={"scope": "library"})
        self.assertEqual(full.status_code, 200)
        with self.open_zip(full) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["counts"]["documents"], 2)
            contents = "\n".join(archive.read(name).decode("utf-8") for name in archive.namelist())
            self.assertIn("FIRST_EDITED", contents)
            self.assertIn("SECOND_MUST_NOT_LEAK", contents)

    def test_exports_require_authentication(self):
        self.client.post("/v1/auth/logout")
        self.assertEqual(self.client.get(
            "/v1/exports/markdown", params={"scope": "library"},
        ).status_code, 401)
        self.assertEqual(self.client.get(
            "/v1/exports/knowledge-package", params={"scope": "library"},
        ).status_code, 401)


if __name__ == "__main__":
    unittest.main()
