import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app import main
from app.ai import (
    AIProviderError, ExtractionResult, KnowledgeUnit, LocalDemoAI,
    MergeProposal, OCRResult,
)
from app.image_ingestion import TEMP_ROOT, combine_ocr_text
from app.store import Store


def png_bytes(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(output, format="PNG")
    return output.getvalue()


class SequenceOCR:
    provider = "test"
    model = "test-ocr"

    def recognize(self, data_url: str, *, source_id: str, sequence: int) -> OCRResult:
        time.sleep((4 - sequence) * 0.005)
        self.assert_safe_data_url(data_url)
        return OCRResult(text=f"第 {sequence} 张图片的识别内容")

    @staticmethod
    def assert_safe_data_url(data_url: str) -> None:
        if not data_url.startswith("data:image/png;base64,"):
            raise AssertionError("OCR did not receive a PNG data URL")


class FailingOCR(SequenceOCR):
    def recognize(self, data_url: str, *, source_id: str, sequence: int) -> OCRResult:
        raise AIProviderError("OCR_TIMEOUT", "图片识别超时，请重新上传", retryable=False, status_code=503)


class FailingAI(LocalDemoAI):
    provider = "test"
    model = "failed-text-model"

    def extract_inputs(self, inputs, source_label, **kwargs):
        raise AIProviderError("AI_TIMEOUT", "模型响应超时", retryable=True, status_code=503)


class TopicOCR(SequenceOCR):
    def recognize(self, data_url: str, *, source_id: str, sequence: int) -> OCRResult:
        self.assert_safe_data_url(data_url)
        return OCRResult(text=(
            "Java 集合包含 List、Set 和 Map。"
            if sequence == 1 else
            "数据库事务具有原子性、一致性、隔离性和持久性。"
        ))


class CoverageRepairAI(LocalDemoAI):
    provider = "test"
    model = "coverage-model"

    def __init__(
        self, *, fail_repair: bool = False, omit_plan: bool = False,
        fail_plan_repair: bool = False,
    ):
        self.fail_repair = fail_repair
        self.omit_plan = omit_plan
        self.fail_plan_repair = fail_plan_repair
        self.extract_calls: list[dict] = []
        self.plan_calls: list[dict] = []

    @staticmethod
    def unit(item) -> KnowledgeUnit:
        subject = "Java 集合" if item.input_index == 1 else "数据库事务"
        return KnowledgeUnit(
            input_index=item.input_index, type="fact", subject=subject,
            content=item.content, source_span=item.content, confidence=0.9,
        )

    def extract_inputs(self, inputs, source_label, **kwargs):
        repair = kwargs.get("repair", False)
        self.extract_calls.append({
            "indexes": [item.input_index for item in inputs],
            "repair": repair,
            "instruction": kwargs.get("analysis_instruction"),
        })
        selected = [] if repair and self.fail_repair else inputs
        if not repair:
            selected = [inputs[0]]
        if not selected:
            # Deliberately invalid evidence keeps the input uncovered after validation.
            selected = [inputs[0]]
            unit = self.unit(selected[0]).model_copy(update={"source_span": "不存在的证据"})
            return ExtractionResult(units=[unit])
        return ExtractionResult(units=[self.unit(item) for item in selected])

    def plan_units(self, units, candidates, source_label, **kwargs):
        repair = kwargs.get("repair", False)
        self.plan_calls.append({
            "refs": [unit.ref for unit in units], "repair": repair,
            "instruction": kwargs.get("analysis_instruction"),
        })
        if repair and self.fail_plan_repair:
            return []
        selected = units[:1] if self.omit_plan and not repair else units
        if self.omit_plan and repair and self.fail_repair:
            selected = units[:1]
        groups = {}
        for unit in selected:
            groups.setdefault(unit.input_index, []).append(unit)
        return [MergeProposal(
            operation="CREATE_DOCUMENT", unit_refs=[unit.ref for unit in grouped],
            target_document_id=None, target_title=("Java 集合" if index == 1 else "数据库事务"),
            reason="按不同主题拆分文档", before=None,
            after="\n\n".join(unit.content for unit in grouped),
            evidence=grouped[0].source_span, confidence=0.9,
        ) for index, grouped in groups.items()]


class ImageIngestionApiTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = (Path(self.tempdir.name) / "image.db").as_posix()
        self.original_store = main.store
        self.original_ai = main.ai
        self.original_ocr = main.ocr
        main.store = Store(f"sqlite+pysqlite:///{db_path}")
        main.ai = LocalDemoAI()
        main.ocr = SequenceOCR()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        main.store.close()
        main.store = self.original_store
        main.ai = self.original_ai
        main.ocr = self.original_ocr
        self.tempdir.cleanup()

    def login(self, email: str = "images@example.com") -> dict:
        captured = {}
        with patch("app.main.send_registration_code", side_effect=lambda target, code: captured.update(code=code)):
            sent = self.client.post("/v1/auth/verification-codes", json={"email": email})
        self.assertEqual(sent.status_code, 204)
        response = self.client.post("/v1/auth/code-login", json={
            "email": email, "verification_code": captured["code"],
        })
        self.assertEqual(response.status_code, 200)
        return response.json()

    def upload(self, images: list[bytes], *, title: str = "图片资料", note: str = "用户说明"):
        return self.client.post(
            "/v1/image-ingestions",
            files=[("files", (f"private-{index}.png", content, "image/png")) for index, content in enumerate(images)],
            data={"title": title, "note": note},
        )

    def test_multiple_images_are_ordered_and_only_analysis_is_persisted(self):
        user = self.login()
        existing_dirs = set(TEMP_ROOT.iterdir()) if TEMP_ROOT.exists() else set()
        response = self.upload([
            png_bytes((255, 0, 0)), png_bytes((0, 255, 0)), png_bytes((0, 0, 255)),
        ])
        self.assertEqual(response.status_code, 202)
        source_id = response.json()["source_id"]
        processing = self.client.get(f"/v1/sources/{source_id}/processing")
        self.assertEqual(processing.status_code, 200)
        self.assertEqual(processing.json()["status"], "proposed")
        self.assertEqual(processing.json()["processed_inputs"], 3)
        self.assertIsNotNone(processing.json()["change_set_id"])

        source = main.store.get_source(user["id"], source_id)
        self.assertLess(source["content"].index("第 1 张"), source["content"].index("第 2 张"))
        self.assertLess(source["content"].index("第 2 张"), source["content"].index("第 3 张"))
        self.assertNotIn("private-", source["content"])
        self.assertNotIn("base64", source["content"])
        self.assertNotIn(str(TEMP_ROOT), source["content"])
        remaining_dirs = set(TEMP_ROOT.iterdir()) if TEMP_ROOT.exists() else set()
        self.assertEqual(remaining_dirs, existing_dirs)

    def test_invalid_and_duplicate_images_are_rejected_before_source_creation(self):
        user = self.login()
        invalid = self.client.post(
            "/v1/image-ingestions",
            files=[("files", ("fake.png", b"not-an-image", "image/png"))],
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.json()["error"]["code"], "IMAGE_INVALID")

        same = png_bytes((20, 30, 40))
        duplicate = self.upload([same, same])
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(duplicate.json()["error"]["code"], "IMAGE_DUPLICATE")
        with main.store.engine.connect() as db:
            from app.store import sources
            rows = db.execute(sources.select().where(sources.c.user_id == user["id"])).all()
        self.assertEqual(rows, [])

    def test_upload_limits_pixels_animation_and_ocr_output_are_rejected(self):
        self.login("limits-images@example.com")

        too_many = self.upload([png_bytes((index, 0, 0)) for index in range(11)])
        self.assertEqual(too_many.status_code, 400)
        self.assertEqual(too_many.json()["error"]["code"], "IMAGE_COUNT_INVALID")

        with patch("app.image_ingestion.MAX_BATCH_BYTES", 100):
            too_large = self.upload([png_bytes((1, 2, 3))])
        self.assertEqual(too_large.status_code, 400)
        self.assertEqual(too_large.json()["error"]["code"], "IMAGE_BATCH_TOO_LARGE")

        with patch("app.image_ingestion.MAX_IMAGE_PIXELS", 100):
            too_many_pixels = self.upload([png_bytes((2, 3, 4))])
        self.assertEqual(too_many_pixels.status_code, 400)
        self.assertEqual(too_many_pixels.json()["error"]["code"], "IMAGE_PIXEL_LIMIT_EXCEEDED")

        animation = io.BytesIO()
        frames = [Image.new("RGB", (8, 8), color) for color in ((255, 0, 0), (0, 0, 255))]
        frames[0].save(
            animation, format="WEBP", save_all=True, append_images=frames[1:], duration=100,
        )
        animated = self.client.post(
            "/v1/image-ingestions",
            files=[("files", ("animated.webp", animation.getvalue(), "image/webp"))],
        )
        self.assertEqual(animated.status_code, 400)
        self.assertEqual(animated.json()["error"]["code"], "IMAGE_ANIMATION_UNSUPPORTED")

        with patch("app.image_ingestion.MAX_COMBINED_OCR_CHARS", 20):
            with self.assertRaisesRegex(ValueError, "100,000"):
                combine_ocr_text(None, ["识别内容" * 10])

    def test_ocr_failure_requires_reupload_and_is_user_scoped(self):
        user = self.login("owner-images@example.com")
        main.ocr = FailingOCR()
        failed = self.upload([png_bytes((10, 20, 30))])
        self.assertEqual(failed.status_code, 202)
        source_id = failed.json()["source_id"]
        own_status = self.client.get(f"/v1/sources/{source_id}/processing").json()
        self.assertEqual(own_status["status"], "failed")
        self.assertTrue(own_status["error"]["requires_reupload"])
        retry = self.client.post(f"/v1/sources/{source_id}/retry")
        self.assertEqual(retry.status_code, 409)
        self.assertEqual(retry.json()["error"]["code"], "IMAGE_REUPLOAD_REQUIRED")
        source = main.store.get_source(user["id"], source_id)
        self.assertNotIn("data:image", source["content"])

        self.client.post("/v1/auth/logout")
        self.login("other-images@example.com")
        self.assertEqual(self.client.get(f"/v1/sources/{source_id}/processing").status_code, 404)
        self.assertEqual(self.client.post(f"/v1/sources/{source_id}/retry").status_code, 404)

    def test_downstream_failure_reuses_saved_ocr_without_image(self):
        self.login("retry-images@example.com")
        main.ai = FailingAI()
        response = self.upload([png_bytes((60, 70, 80))])
        source_id = response.json()["source_id"]
        failed = self.client.get(f"/v1/sources/{source_id}/processing").json()
        self.assertEqual(failed["error"]["code"], "AI_TIMEOUT")
        self.assertFalse(failed["error"]["requires_reupload"])

        main.ai = LocalDemoAI()
        retried = self.client.post(f"/v1/sources/{source_id}/retry")
        self.assertEqual(retried.status_code, 202)
        complete = self.client.get(f"/v1/sources/{source_id}/processing").json()
        self.assertEqual(complete["status"], "proposed")
        self.assertIsNotNone(complete["change_set_id"])

    def test_missing_database_topic_is_repaired_and_split_into_two_drafts(self):
        self.login("coverage-images@example.com")
        main.ocr = TopicOCR()
        repair_ai = CoverageRepairAI(omit_plan=True)
        main.ai = repair_ai

        response = self.upload(
            [png_bytes((101, 1, 1)), png_bytes((1, 101, 1))],
            title="java八股文", note="请完整整理",
        )
        self.assertEqual(response.status_code, 202)
        source_id = response.json()["source_id"]
        status_result = self.client.get(f"/v1/sources/{source_id}/processing").json()
        self.assertEqual(status_result["status"], "proposed")
        self.assertEqual(status_result["covered_inputs"], 2)
        self.assertEqual(status_result["extraction_attempts"], 2)
        self.assertEqual(
            [item["knowledge_unit_count"] for item in status_result["input_coverage"]],
            [1, 1],
        )
        self.assertEqual(repair_ai.extract_calls[0]["indexes"], [1, 2])
        self.assertEqual(repair_ai.extract_calls[1], {
            "indexes": [2], "repair": True, "instruction": None,
        })
        self.assertEqual([call["repair"] for call in repair_ai.plan_calls], [False, True])
        draft = self.client.get(
            f"/v1/change-sets/{status_result['change_set_id']}"
        ).json()
        self.assertEqual({item["target_title"] for item in draft["items"]}, {
            "Java 集合", "数据库事务",
        })

    def test_incomplete_coverage_fails_without_persisting_partial_units(self):
        user = self.login("incomplete-images@example.com")
        main.ocr = TopicOCR()
        main.ai = CoverageRepairAI(fail_repair=True)
        response = self.upload([png_bytes((102, 1, 1)), png_bytes((1, 102, 1))])
        source_id = response.json()["source_id"]
        result = self.client.get(f"/v1/sources/{source_id}/processing").json()
        self.assertEqual(result["error"]["code"], "AI_INCOMPLETE_COVERAGE")
        self.assertIsNone(result["change_set_id"])
        with main.store.engine.connect() as db:
            from app.store import knowledge_units
            count = db.execute(knowledge_units.count() if hasattr(knowledge_units, "count") else knowledge_units.select().where(
                knowledge_units.c.user_id == user["id"], knowledge_units.c.source_id == source_id,
            )).all()
        self.assertEqual(count, [])

    def test_incomplete_plan_fails_without_creating_partial_draft(self):
        self.login("incomplete-plan@example.com")
        main.ocr = TopicOCR()
        main.ai = CoverageRepairAI(omit_plan=True, fail_plan_repair=True)
        response = self.upload([png_bytes((105, 1, 1)), png_bytes((1, 105, 1))])
        source_id = response.json()["source_id"]
        result = self.client.get(f"/v1/sources/{source_id}/processing").json()
        self.assertEqual(result["error"]["code"], "AI_INCOMPLETE_PLAN")
        self.assertIsNone(result["change_set_id"])

    def test_reprocess_reuses_ocr_keeps_instruction_and_supersedes_only_on_success(self):
        self.login("reprocess-images@example.com")
        main.ocr = TopicOCR()
        main.ai = LocalDemoAI()
        created = self.upload([png_bytes((103, 1, 1)), png_bytes((1, 103, 1))])
        source_id = created.json()["source_id"]
        before = self.client.get(f"/v1/sources/{source_id}/processing").json()
        old_draft_id = before["change_set_id"]

        repair_ai = CoverageRepairAI()
        main.ai = repair_ai
        response = self.client.post(f"/v1/sources/{source_id}/reprocess", json={
            "instruction": "数据库内容单独成文档，标题明确",
        })
        self.assertEqual(response.status_code, 202)
        after = self.client.get(f"/v1/sources/{source_id}/processing").json()
        self.assertNotEqual(after["change_set_id"], old_draft_id)
        old_draft = self.client.get(f"/v1/change-sets/{old_draft_id}").json()
        new_draft = self.client.get(f"/v1/change-sets/{after['change_set_id']}").json()
        self.assertEqual(old_draft["status"], "superseded")
        self.assertEqual(new_draft["supersedes_change_set_id"], old_draft_id)
        self.assertEqual(new_draft["analysis_instruction"], "数据库内容单独成文档，标题明确")
        self.assertEqual(repair_ai.extract_calls[0]["instruction"], "数据库内容单独成文档，标题明确")
        self.assertEqual(self.client.post(
            f"/v1/change-sets/{old_draft_id}/apply", json={"accepted_item_ids": None},
        ).status_code, 404)
        applied = self.client.post(
            f"/v1/change-sets/{new_draft['id']}/apply", json={"accepted_item_ids": None},
        )
        self.assertEqual(applied.status_code, 200)
        rejected = self.client.post(f"/v1/sources/{source_id}/reprocess", json={})
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.json()["error"]["code"], "SOURCE_ALREADY_APPLIED")

    def test_failed_reprocess_leaves_previous_draft_available(self):
        self.login("failed-reprocess@example.com")
        main.ocr = TopicOCR()
        main.ai = LocalDemoAI()
        created = self.upload([png_bytes((104, 1, 1)), png_bytes((1, 104, 1))])
        source_id = created.json()["source_id"]
        old_id = self.client.get(f"/v1/sources/{source_id}/processing").json()["change_set_id"]
        main.ai = CoverageRepairAI(fail_repair=True)
        response = self.client.post(f"/v1/sources/{source_id}/reprocess", json={})
        self.assertEqual(response.status_code, 202)
        failed = self.client.get(f"/v1/sources/{source_id}/processing").json()
        self.assertEqual(failed["error"]["code"], "AI_INCOMPLETE_COVERAGE")
        self.assertEqual(failed["change_set_id"], old_id)
        self.assertEqual(self.client.get(f"/v1/change-sets/{old_id}").json()["status"], "proposed")

    def test_restart_distinguishes_unrecoverable_ocr_from_saved_text(self):
        user = self.login("restart-images@example.com")
        queued = main.store.create_image_source(
            user["id"], title="queued", total_inputs=1,
            ocr_model="test-ocr", ocr_prompt_version="ocr-v1",
        )
        self.assertEqual(queued["content"], "")

        saved = main.store.create_image_source(
            user["id"], title="saved", total_inputs=1,
            ocr_model="test-ocr", ocr_prompt_version="ocr-v1",
        )
        main.store.start_image_ocr(user["id"], saved["id"])
        main.store.save_ocr_content(user["id"], saved["id"], "# 图片 1 OCR\n\n已保存文字")

        self.assertEqual(main.store.fail_interrupted_image_sources(), 2)
        queued_status = self.client.get(f"/v1/sources/{queued['id']}/processing").json()
        saved_status = self.client.get(f"/v1/sources/{saved['id']}/processing").json()
        self.assertEqual(queued_status["error"]["code"], "WORKER_INTERRUPTED")
        self.assertTrue(queued_status["error"]["requires_reupload"])
        self.assertEqual(saved_status["error"]["code"], "AI_WORKER_INTERRUPTED")
        self.assertFalse(saved_status["error"]["requires_reupload"])


if __name__ == "__main__":
    unittest.main()
