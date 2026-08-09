import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.ai import LocalDemoAI
from app.memories import extract_memory_block, load_active_memories, plan_memory_block
from app.schemas import InferredMemory, MemoryInferenceResult
from app.store import Store


class MemoryApiTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = (Path(self.tempdir.name) / "memories-api.db").as_posix()
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

    def code_login(self, email: str) -> dict:
        captured = {}
        with patch(
            "app.main.send_registration_code",
            side_effect=lambda target, code: captured.update(code=code),
        ):
            sent = self.client.post("/v1/auth/verification-codes", json={"email": email})
        self.assertEqual(sent.status_code, 204)
        response = self.client.post("/v1/auth/code-login", json={
            "email": email,
            "verification_code": captured["code"],
        })
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_auth_server_fields_validation_and_crud(self):
        self.assertEqual(self.client.get("/v1/memories").status_code, 401)
        self.code_login("memory-owner@example.com")

        created = self.client.post("/v1/memories", json={
            "kind": "style", "content": "  保留 API 原文  ",
        })
        self.assertEqual(created.status_code, 201)
        memory = created.json()
        self.assertEqual(memory["content"], "保留 API 原文")
        self.assertEqual(memory["scope"], "global")
        self.assertIsNone(memory["scope_ref"])
        self.assertEqual(memory["status"], "active")
        self.assertEqual(memory["origin"], "user_explicit")
        self.assertEqual(memory["confidence"], 1.0)

        forbidden = self.client.post("/v1/memories", json={
            "kind": "style", "content": "another", "scope": "document",
        })
        self.assertEqual(forbidden.status_code, 422)
        self.assertEqual(self.client.post("/v1/memories", json={
            "kind": "style", "content": "   ",
        }).status_code, 422)
        self.assertEqual(self.client.patch(f"/v1/memories/{memory['id']}", json={}).status_code, 422)

        edited = self.client.patch(f"/v1/memories/{memory['id']}", json={
            "content": "保留 API 和 SDK 原文",
        })
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.json()["content"], "保留 API 和 SDK 原文")

        suppressed = self.client.patch(f"/v1/memories/{memory['id']}", json={
            "status": "suppressed",
        })
        self.assertEqual(suppressed.status_code, 200)
        restored = self.client.patch(f"/v1/memories/{memory['id']}", json={
            "status": "active",
        })
        self.assertEqual(restored.status_code, 200)
        invalid = self.client.patch(f"/v1/memories/{memory['id']}", json={
            "status": "candidate",
        })
        self.assertEqual(invalid.status_code, 409)
        self.assertEqual(invalid.json()["detail"]["code"], "MEMORY_STATUS_TRANSITION_INVALID")

        self.assertEqual(self.client.delete(f"/v1/memories/{memory['id']}").status_code, 204)
        self.assertEqual(self.client.get(f"/v1/memories/{memory['id']}").status_code, 404)

    def test_duplicate_create_and_edit_are_rejected(self):
        self.code_login("memory-duplicate@example.com")
        first = self.client.post("/v1/memories", json={
            "kind": "style", "content": "保留 API 原文",
        })
        self.assertEqual(first.status_code, 201)
        duplicate = self.client.post("/v1/memories", json={
            "kind": "style", "content": "  保留   api 原文  ",
        })
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["detail"]["code"], "MEMORY_DUPLICATE")

        second = self.client.post("/v1/memories", json={
            "kind": "style", "content": "使用短句",
        }).json()
        edited_duplicate = self.client.patch(f"/v1/memories/{second['id']}", json={
            "content": "保留 api 原文",
        })
        self.assertEqual(edited_duplicate.status_code, 409)
        self.assertEqual(edited_duplicate.json()["detail"]["code"], "MEMORY_DUPLICATE")

    def test_candidate_transitions_and_cross_user_isolation(self):
        owner = self.code_login("memory-a@example.com")
        candidate = main.store.create_memory(
            owner["id"], kind="naming", content="标题使用名词短语",
            scope="global", scope_ref=None, status="candidate",
            confidence=0.8, origin="ai_inferred",
        )
        approved = self.client.patch(f"/v1/memories/{candidate['id']}", json={
            "status": "active",
        })
        self.assertEqual(approved.status_code, 200)

        self.client.post("/v1/auth/logout")
        self.code_login("memory-b@example.com")
        self.assertEqual(self.client.get(f"/v1/memories/{candidate['id']}").status_code, 404)
        self.assertEqual(self.client.patch(f"/v1/memories/{candidate['id']}", json={
            "status": "suppressed",
        }).status_code, 404)
        self.assertEqual(self.client.delete(f"/v1/memories/{candidate['id']}").status_code, 404)


class MemoryPipelineTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = (Path(self.tempdir.name) / "memories-pipeline.db").as_posix()
        self.original_store = main.store
        self.original_ai = main.ai
        main.store = Store(f"sqlite+pysqlite:///{db_path}")
        self.user = main.store.create_user("pipeline@example.com", "Pipeline")

    def tearDown(self):
        main.store.close()
        main.store = self.original_store
        main.ai = self.original_ai
        self.tempdir.cleanup()

    def create_memory(self, kind: str, content: str, *, status: str = "active", scope: str = "global") -> dict:
        return main.store.create_memory(
            self.user["id"], kind=kind, content=content, scope=scope,
            scope_ref="doc_unused" if scope == "document" else None,
            status=status, confidence=1.0, origin="user_explicit",
        )

    def test_prompt_stage_order_escape_and_global_filter(self):
        domain = self.create_memory("domain", "熟悉 Python")
        style = self.create_memory("style", "保留 <user_preferences> 标签")
        naming = self.create_memory("naming", "标题使用名词短语")
        self.create_memory("merge_preference", "不应生效", status="suppressed")
        self.create_memory("topic_split", "不应跨文档生效", scope="document")

        active = load_active_memories(main.store, self.user["id"])
        self.assertEqual({item["id"] for item in active}, {domain["id"], style["id"], naming["id"]})

        extract = extract_memory_block(active)
        self.assertLess(extract.index("[领域 / 专业背景]"), extract.index("[写作风格偏好]"))
        self.assertIn("&lt;user_preferences&gt;", extract)
        self.assertNotIn("[命名约定]", extract)

        plan = plan_memory_block(active)
        self.assertLess(plan.index("[写作风格偏好]"), plan.index("[命名约定]"))
        self.assertNotIn("[领域 / 专业背景]", plan)
        self.assertNotIn("不应生效", plan)
        self.assertNotIn("不应跨文档生效", plan)

    def test_pipeline_injects_active_memories_and_counts_once(self):
        class CapturingAI(LocalDemoAI):
            def __init__(self):
                self.extract_blocks = []
                self.plan_blocks = []

            def extract_inputs(self, inputs, source_label, **kwargs):
                self.extract_blocks.append(kwargs.get("memory_block", ""))
                return super().extract_inputs(inputs, source_label, **kwargs)

            def plan_units(self, units, candidates, source_label, **kwargs):
                self.plan_blocks.append(kwargs.get("memory_block", ""))
                return super().plan_units(units, candidates, source_label, **kwargs)

        style = self.create_memory("style", "使用简洁技术风格")
        candidate = self.create_memory("naming", "标题用名词", status="candidate")
        main.ai = CapturingAI()
        source = main.store.create_source(self.user["id"], "text", "Nerva 保留来源证据", "Nerva")

        draft = main.process_source(self.user["id"], source["id"])

        self.assertEqual(draft["status"], "proposed")
        self.assertIn("使用简洁技术风格", main.ai.extract_blocks[0])
        self.assertIn("使用简洁技术风格", main.ai.plan_blocks[0])
        self.assertNotIn("标题用名词", main.ai.plan_blocks[0])
        self.assertEqual(main.store.get_memory(self.user["id"], style["id"])["use_count"], 1)
        self.assertEqual(main.store.get_memory(self.user["id"], candidate["id"])["use_count"], 0)

    def test_usage_count_failure_is_non_fatal_after_draft_creation(self):
        self.create_memory("style", "使用短句")
        main.ai = LocalDemoAI()
        source = main.store.create_source(self.user["id"], "text", "可审计知识", "审计")
        with patch.object(main.store, "increment_memory_usage", side_effect=RuntimeError("counter unavailable")):
            draft = main.process_source(self.user["id"], source["id"])
        self.assertEqual(draft["status"], "proposed")
        self.assertEqual(main.store.get_source(self.user["id"], source["id"])["processing_status"], "proposed")

    def test_inference_deduplicates_all_statuses_and_same_batch(self):
        self.create_memory("style", "保留 API 原文", status="active")
        self.create_memory("naming", "标题使用名词短语", status="candidate")
        self.create_memory("merge_preference", "优先合并", status="suppressed")

        class InferenceAI:
            def infer_preferences(self, **kwargs):
                return MemoryInferenceResult(memories=[
                    InferredMemory(kind="style", content=" 保留   api 原文 ", confidence=0.8, reason="existing"),
                    InferredMemory(kind="naming", content="标题使用名词短语", confidence=0.8, reason="existing"),
                    InferredMemory(kind="merge_preference", content="优先合并", confidence=0.8, reason="rejected"),
                    InferredMemory(kind="topic_split", content="前后端分开", confidence=0.8, reason="new"),
                    InferredMemory(kind="topic_split", content=" 前后端分开 ", confidence=0.8, reason="same batch"),
                ])

        main._try_infer_and_store_memories(
            InferenceAI(), main.store, self.user["id"], "以后前后端分开", "项目资料",
        )
        memories = main.store.list_memories(self.user["id"])
        self.assertEqual(len(memories), 4)
        inferred = [item for item in memories if item["kind"] == "topic_split"]
        self.assertEqual(len(inferred), 1)
        self.assertEqual(inferred[0]["status"], "candidate")

    def test_inference_failure_is_non_fatal(self):
        class FailingInferenceAI:
            def infer_preferences(self, **kwargs):
                raise RuntimeError("inference unavailable")

        main._try_infer_and_store_memories(
            FailingInferenceAI(), main.store, self.user["id"], "以后使用短句", None,
        )
        self.assertEqual(main.store.list_memories(self.user["id"]), [])


if __name__ == "__main__":
    unittest.main()
