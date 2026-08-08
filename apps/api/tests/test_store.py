import tempfile
import unittest
from pathlib import Path

from sqlalchemy import insert, select

from app.ai import LocalDemoAI, MergeProposal
from app.store import DocumentVersionConflict, LEGACY_USER_ID, Store, now_utc, sources, users


class KnowledgeFlowTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = (Path(self.tempdir.name) / "test.db").as_posix()
        self.store = Store(f"sqlite+pysqlite:///{db_path}")
        self.ai = LocalDemoAI()
        self.user = self.store.create_user("owner@example.com", "Owner")

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def test_create_then_merge_and_log(self):
        first = "FastAPI Middleware 在路由之前执行，可用于日志与鉴权。"
        proposal = self.ai.propose(first, "FastAPI Middleware", [])
        change_set = self.store.create_change_set(self.user["id"], "text", first, "FastAPI Middleware", proposal)
        self.store.apply_change_set(self.user["id"], change_set["id"], None)

        documents = self.store.list_documents(self.user["id"])
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["version"], 1)

        second = "FastAPI Middleware 也可以统一添加请求 ID。"
        proposal = self.ai.propose(second, "FastAPI Middleware", documents)
        self.assertEqual(proposal.operation, "ADD_BLOCK")
        change_set = self.store.create_change_set(self.user["id"], "text", second, "FastAPI Middleware", proposal)
        self.store.apply_change_set(self.user["id"], change_set["id"], None)

        documents = self.store.list_documents(self.user["id"])
        self.assertEqual(documents[0]["version"], 2)
        self.assertIn("请求 ID", documents[0]["markdown"])
        self.assertEqual(len(self.store.list_events(self.user["id"])), 2)

    def test_change_detail_keeps_source_decisions_and_created_document_link(self):
        content = "An auditable source"
        draft = self.store.create_change_set(
            self.user["id"], "text", content, "Audit",
            self.ai.propose(content, "Audit", []),
        )
        self.assertEqual(draft["origin"], "ai_ingestion")
        self.assertEqual(draft["source"]["content"], content)
        applied = self.store.apply_change_set(self.user["id"], draft["id"], None)
        self.assertTrue(applied["items"][0]["accepted"])
        self.assertIsNotNone(applied["items"][0]["target_document_id"])

    def test_manual_edit_creates_version_change_set_and_event(self):
        initial = self.store.create_change_set(
            self.user["id"], "text", "Initial", "Topic",
            self.ai.propose("Initial", "Topic", []),
        )
        self.store.apply_change_set(self.user["id"], initial["id"], None)
        document = self.store.list_documents(self.user["id"])[0]

        updated = self.store.update_document(
            self.user["id"], document["id"], title="Renamed Topic",
            markdown="# Renamed Topic\n\nEdited", base_version=1, reason="clarify",
        )
        self.assertEqual(updated["version"], 2)
        self.assertEqual(updated["title"], "Renamed Topic")
        versions = self.store.list_document_versions(self.user["id"], document["id"])
        self.assertEqual([item["version"] for item in versions], [2, 1])
        self.assertEqual(versions[0]["title"], "Renamed Topic")
        self.assertEqual(versions[1]["title"], "Topic")

        event = self.store.list_events(self.user["id"])[0]
        self.assertEqual(event["origin"], "manual_edit")
        detail = self.store.get_change_set(self.user["id"], event["change_set_id"])
        self.assertIsNone(detail["source"])
        self.assertEqual(detail["items"][0]["operation"], "UPDATE_DOCUMENT")
        self.assertEqual(detail["items"][0]["before_title"], "Topic")
        self.assertTrue(detail["items"][0]["accepted"])

        with self.assertRaises(DocumentVersionConflict):
            self.store.update_document(
                self.user["id"], document["id"], title="Stale",
                markdown="Stale", base_version=1, reason=None,
            )

    def test_manual_noop_does_not_create_version_or_event(self):
        initial = self.store.create_change_set(
            self.user["id"], "text", "Initial", "Topic",
            self.ai.propose("Initial", "Topic", []),
        )
        self.store.apply_change_set(self.user["id"], initial["id"], None)
        document = self.store.list_documents(self.user["id"])[0]
        before_events = len(self.store.list_events(self.user["id"]))
        unchanged = self.store.update_document(
            self.user["id"], document["id"], title=document["title"],
            markdown=document["markdown"], base_version=document["version"], reason="ignored",
        )
        self.assertEqual(unchanged["version"], 1)
        self.assertEqual(len(self.store.list_document_versions(self.user["id"], document["id"])), 1)
        self.assertEqual(len(self.store.list_events(self.user["id"])), before_events)

    def test_first_user_claims_legacy_data(self):
        with self.store.engine.begin() as db:
            db.execute(insert(users).values(
                id=LEGACY_USER_ID, email="legacy@nerva.invalid", display_name="Legacy",
                status="disabled", created_at=now_utc(), updated_at=now_utc(),
            ))
            db.execute(insert(sources).values(
                id="src_legacy", user_id=LEGACY_USER_ID, kind="text", title="Legacy",
                content="legacy content", processing_status="received", created_at=now_utc(),
            ))
        claimed = self.store.create_user("claim@example.com", "Claim")
        with self.store.engine.connect() as db:
            owner = db.execute(select(sources.c.user_id).where(sources.c.id == "src_legacy")).scalar_one()
            legacy = db.execute(select(users.c.id).where(users.c.id == LEGACY_USER_ID)).first()
        self.assertEqual(owner, claimed["id"])
        self.assertIsNone(legacy)

    def test_multiple_changes_only_mutating_operations_edit_markdown(self):
        initial = self.store.create_change_set(
            self.user["id"], "text", "Initial", "Topic",
            self.ai.propose("Initial", "Topic", []),
        )
        self.store.apply_change_set(self.user["id"], initial["id"], None)
        document = self.store.list_documents(self.user["id"])[0]
        source = self.store.create_source(self.user["id"], "text", "New and conflicting", "Topic")
        self.store.claim_source_for_processing(
            self.user["id"], source["id"], provider="test", model="test",
            prompt_version="test-v1",
        )
        common = {
            "unit_refs": ["unit_001"],
            "target_document_id": document["id"], "target_title": document["title"],
            "before": document["markdown"], "evidence": "New and conflicting",
        }
        proposals = [
            MergeProposal(operation="ADD_BLOCK", reason="new", after="## New\n\nContent", confidence=0.9, **common),
            MergeProposal(operation="MARK_DUPLICATE", reason="duplicate", after="Duplicate", confidence=0.8, **common),
            MergeProposal(operation="REPORT_CONFLICT", reason="conflict", after="Conflict", confidence=0.7, **common),
        ]
        draft = self.store.create_change_set_for_source(self.user["id"], source["id"], proposals)
        self.assertEqual(len(draft["items"]), 3)
        self.store.apply_change_set(self.user["id"], draft["id"], None)
        updated = self.store.list_documents(self.user["id"])[0]
        self.assertEqual(updated["version"], 2)
        self.assertIn("## New", updated["markdown"])
        self.assertNotIn("Duplicate", updated["markdown"])
        self.assertNotIn("Conflict", updated["markdown"])
        event = self.store.list_events(self.user["id"])[0]
        self.assertEqual(event["accepted_count"], 3)

    def test_change_set_rejects_other_users_document_target(self):
        other = self.store.create_user("other@example.com", "Other")
        initial = self.store.create_change_set(
            other["id"], "text", "Private", "Private",
            self.ai.propose("Private", "Private", []),
        )
        self.store.apply_change_set(other["id"], initial["id"], None)
        target = self.store.list_documents(other["id"])[0]
        source = self.store.create_source(self.user["id"], "text", "Attack", "Attack")
        self.store.claim_source_for_processing(
            self.user["id"], source["id"], provider="test", model="test",
            prompt_version="test-v1",
        )
        proposal = MergeProposal(
            operation="ADD_BLOCK", unit_refs=["unit_001"],
            target_document_id=target["id"], target_title=target["title"],
            reason="attack", before=target["markdown"], after="Injected",
            evidence="Attack", confidence=0.9,
        )
        with self.assertRaises(ValueError):
            self.store.create_change_set_for_source(self.user["id"], source["id"], [proposal])


if __name__ == "__main__":
    unittest.main()
