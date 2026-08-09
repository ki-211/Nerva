import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.ai import LocalDemoAI
from app.retrieval import HybridRetriever, chunk_markdown, rebuild_document_index
from app.store import Store


class HybridRetrievalTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        path = (Path(self.tempdir.name) / "retrieval.db").as_posix()
        self.store = Store(f"sqlite+pysqlite:///{path}")
        self.ai = LocalDemoAI()
        self.user = self.store.create_user("retrieval@example.com", "Retrieval")

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def create_document(self, title: str, content: str, user_id: str | None = None) -> dict:
        owner = user_id or self.user["id"]
        proposal = self.ai.propose(content, title, [])
        draft = self.store.create_change_set(owner, "text", content, title, proposal)
        self.store.apply_change_set(owner, draft["id"], None)
        return self.store.list_documents(owner)[0]

    def test_chunking_is_stable_and_preserves_structures(self):
        markdown = """# API

Intro paragraph.

- one
- two

```python
print('safe')
print('still fenced')
```

| A | B |
|---|---|
| 1 | 2 |
"""
        first = chunk_markdown("Guide", markdown, target_chars=80, overlap_chars=12, max_chars=180)
        second = chunk_markdown("Guide", markdown, target_chars=80, overlap_chars=12, max_chars=180)
        self.assertEqual(first, second)
        self.assertEqual(sum(chunk.count("```") for chunk in first) % 2, 0)
        self.assertTrue(any("| A | B |\n|---|---|\n| 1 | 2 |" in chunk for chunk in first))
        self.assertTrue(all(chunk.startswith("# Guide") for chunk in first))

    def test_hybrid_retrieval_reindex_and_user_isolation(self):
        document = self.create_document("Orion", "Orion service listens on port 8443.")
        chunks = rebuild_document_index(self.store, self.user["id"], document["id"], self.ai)
        self.assertEqual(chunks[0]["embedding_status"], "ready")
        self.assertEqual(len(chunks[0]["embedding"]), 1024)
        again = rebuild_document_index(self.store, self.user["id"], document["id"], self.ai)
        self.assertEqual(len(again), len(chunks))

        other = self.store.create_user("other-retrieval@example.com", "Other")
        other_document = self.create_document("Private", "Orion secret port 9999", other["id"])
        rebuild_document_index(self.store, other["id"], other_document["id"], self.ai)
        result = HybridRetriever(self.store, self.ai).retrieve(self.user["id"], "Orion port")
        self.assertEqual(result.retrieval_mode, "hybrid")
        self.assertEqual({item["document_id"] for item in result.results}, {document["id"]})

    def test_document_update_replaces_old_version_chunks(self):
        document = self.create_document("Versioned", "Legacy marker alpha.")
        rebuild_document_index(self.store, self.user["id"], document["id"], self.ai)
        updated = self.store.update_document(
            self.user["id"], document["id"], title="Versioned",
            markdown="# Versioned\n\nCurrent marker beta.", base_version=1, reason="replace",
        )
        rebuild_document_index(self.store, self.user["id"], document["id"], self.ai)
        chunks = self.store.list_search_chunks(self.user["id"], document["id"])
        self.assertEqual({item["document_version"] for item in chunks}, {updated["version"]})
        self.assertNotIn("Legacy marker alpha", "\n".join(item["content"] for item in chunks))

    def test_embedding_and_rerank_failures_keep_keyword_order(self):
        class FailingProvider(LocalDemoAI):
            def embed(self, texts):
                raise TimeoutError("offline")

            def rerank(self, query, candidates):
                raise ValueError("bad response")

        document = self.create_document("Fallback", "Keyword fallback remains available.")
        self.store.replace_document_chunks(
            self.user["id"], document["id"], document["version"],
            [{"content": "# Fallback\n\nKeyword fallback remains available.", "embedding_status": "failed"}],
        )
        result = HybridRetriever(self.store, FailingProvider()).retrieve(self.user["id"], "Keyword fallback")
        self.assertEqual(result.retrieval_mode, "keyword")
        self.assertEqual(result.results[0]["document_id"], document["id"])
        self.assertIsNotNone(result.fallback_reason)


class SearchApiTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        path = (Path(self.tempdir.name) / "search.db").as_posix()
        self.original_store, self.original_ai = main.store, main.ai
        main.store, main.ai = Store(f"sqlite+pysqlite:///{path}"), LocalDemoAI()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        main.store.close()
        main.store, main.ai = self.original_store, self.original_ai
        self.tempdir.cleanup()

    def login(self, email: str):
        captured = {}
        with patch("app.main.send_registration_code", side_effect=lambda target, code: captured.update(code=code)):
            self.client.post("/v1/auth/verification-codes", json={"email": email})
        return self.client.post("/v1/auth/code-login", json={"email": email, "verification_code": captured["code"]}).json()

    def test_search_validation_reindex_and_isolation(self):
        self.assertEqual(self.client.get("/v1/search", params={"q": "Orion"}).status_code, 401)
        self.login("search@example.com")
        draft = self.client.post("/v1/ingestions", json={"kind": "text", "title": "Orion", "content": "Orion port 8443"}).json()
        self.client.post(f"/v1/change-sets/{draft['id']}/apply", json={"accepted_item_ids": [item["id"] for item in draft["items"]]})
        document = self.client.get("/v1/documents").json()[0]
        self.assertEqual(self.client.get("/v1/search", params={"q": "   "}).status_code, 422)
        self.assertEqual(self.client.get("/v1/search", params={"q": "Orion", "limit": 0}).status_code, 422)
        result = self.client.get("/v1/search", params={"q": "Orion port", "limit": 4}).json()
        self.assertEqual(result["retrieval_mode"], "hybrid")
        self.assertEqual(result["items"][0]["document_id"], document["id"])
        first = self.client.post(f"/v1/documents/{document['id']}/reindex").json()
        second = self.client.post(f"/v1/documents/{document['id']}/reindex").json()
        self.assertEqual(first["chunks"], second["chunks"])

        self.client.post("/v1/auth/logout")
        self.login("search-other@example.com")
        self.assertEqual(self.client.get("/v1/search", params={"q": "Orion"}).json()["items"], [])
        self.assertEqual(self.client.post(f"/v1/documents/{document['id']}/reindex").status_code, 404)


if __name__ == "__main__":
    unittest.main()
