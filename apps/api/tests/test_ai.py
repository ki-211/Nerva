import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.ai import (
    AIProviderError, BailianAI, BailianOCR, ExtractionResult, MergeProposal,
    PlanningUnit, SourceInput, missing_proposal_refs, validate_extraction,
)


def chat_response(content: dict, status_code: int = 200) -> httpx.Response:
    request = httpx.Request("POST", "https://example.test/chat/completions")
    if status_code != 200:
        return httpx.Response(status_code, request=request, json={"error": "upstream"})
    return httpx.Response(status_code, request=request, json={
        "choices": [{"message": {"content": json.dumps(content)}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8},
    })


class BailianAITest(unittest.TestCase):
    def make_ai(self, handler):
        fake_settings = SimpleNamespace(
            validate=lambda: None,
            dashscope_base_url="https://example.test",
            text_model="test-model",
            **{"dashscope_api" + "_key": "test-value"},
        )
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch("app.ai.settings", fake_settings):
            return BailianAI(client=client)

    def test_structured_output_disables_thinking(self):
        captured = {}

        def handler(request):
            captured.update(json.loads(request.content))
            return chat_response({"units": [{
                "input_index": 0, "type": "fact", "subject": "Nerva", "content": "input",
                "source_span": "input", "confidence": 0.9,
            }], "uncertainties": []})

        ai = self.make_ai(handler)
        ai.extract("input", None)

        self.assertIs(captured["enable_thinking"], False)
        self.assertEqual(captured["response_format"], {"type": "json_object"})

    def test_multiple_units_and_changes(self):
        responses = iter([
            chat_response({"units": [
                {"input_index": 0, "type": "fact", "subject": "Nerva", "content": "Supports changes", "source_span": "Supports changes", "confidence": 0.9},
                {"input_index": 0, "type": "action_item", "subject": "Tests", "content": "Add tests", "source_span": "Add tests", "confidence": 0.8},
            ], "uncertainties": []}),
            chat_response({"items": [
                {"operation": "CREATE_DOCUMENT", "unit_refs": ["unit_001"], "target_document_id": None, "target_title": "Nerva", "reason": "new topic", "before": None, "after": "# Nerva", "evidence": "Supports changes", "confidence": 0.9},
                {"operation": "REPORT_CONFLICT", "unit_refs": ["unit_002"], "target_document_id": "doc_1", "target_title": "ignored", "reason": "conflict", "before": "ignored", "after": "new claim", "evidence": "Add tests", "confidence": 0.7},
            ]}),
        ])
        ai = self.make_ai(lambda request: next(responses))
        extraction = ai.extract("Nerva supports changes. Add tests.", "Nerva")
        self.assertEqual(len(extraction.units), 2)
        items = ai.plan(extraction, [{
            "id": "doc_1", "title": "Existing", "version": 2, "markdown": "# Existing",
        }], "Nerva")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[1].target_title, "Existing")
        self.assertEqual(items[1].before, "# Existing")

    def test_invalid_json_is_stable_error(self):
        def handler(request):
            return httpx.Response(200, request=request, json={
                "choices": [{"message": {"content": "not-json"}}],
            })
        ai = self.make_ai(handler)
        with self.assertRaises(AIProviderError) as caught:
            ai.extract("input", None)
        self.assertEqual(caught.exception.code, "AI_INVALID_RESPONSE")

    def test_rate_limit_is_retryable(self):
        ai = self.make_ai(lambda request: httpx.Response(429, request=request, json={"error": "limited"}))
        with self.assertRaises(AIProviderError) as caught:
            ai.extract("input", None)
        self.assertEqual(caught.exception.code, "AI_RATE_LIMITED")
        self.assertTrue(caught.exception.retryable)

    def test_upstream_error_details_are_sanitized(self):
        def handler(request):
            return httpx.Response(
                400,
                request=request,
                headers={"x-request-id": "req-123\nignored"},
                json={"error": {
                    "code": "InvalidParameter",
                    "message": "Json mode response is not supported\nwhen thinking is enabled",
                }},
            )

        ai = self.make_ai(handler)
        with self.assertRaises(AIProviderError) as caught:
            ai.extract("input", None)

        error = caught.exception
        self.assertEqual(error.code, "AI_UPSTREAM_ERROR")
        self.assertFalse(error.retryable)
        self.assertEqual(error.upstream_status, 400)
        self.assertEqual(error.upstream_code, "InvalidParameter")
        self.assertEqual(error.upstream_message, "Json mode response is not supported when thinking is enabled")
        self.assertEqual(error.request_id, "req-123 ignored")

    def test_server_error_remains_retryable(self):
        ai = self.make_ai(lambda request: httpx.Response(
            503,
            request=request,
            json={"code": "ServiceUnavailable", "message": "try again", "request_id": "req-503"},
        ))
        with self.assertRaises(AIProviderError) as caught:
            ai.extract("input", None)

        error = caught.exception
        self.assertEqual(error.code, "AI_UPSTREAM_ERROR")
        self.assertTrue(error.retryable)
        self.assertEqual(error.status_code, 503)
        self.assertEqual(error.upstream_status, 503)
        self.assertEqual(error.request_id, "req-503")

    def test_timeout_is_stable_error(self):
        def handler(request):
            raise httpx.ReadTimeout("timed out", request=request)
        ai = self.make_ai(handler)
        with self.assertRaises(AIProviderError) as caught:
            ai.extract("input", None)
        self.assertEqual(caught.exception.code, "AI_TIMEOUT")
        self.assertTrue(caught.exception.retryable)

    def test_non_candidate_target_is_rejected(self):
        response = chat_response({"items": [{
            "operation": "ADD_BLOCK", "unit_refs": ["unit_001"], "target_document_id": "doc_other", "target_title": "Other",
            "reason": "related", "before": "", "after": "new", "evidence": "input", "confidence": 0.8,
        }]})
        ai = self.make_ai(lambda request: response)
        extraction = ExtractionResult.model_validate({"units": [{
            "input_index": 0, "type": "fact", "subject": "Subject", "content": "input",
            "source_span": "input", "confidence": 0.9,
        }]})
        with self.assertRaises(AIProviderError) as caught:
            ai.plan(extraction, [], None)
        self.assertEqual(caught.exception.code, "AI_INVALID_TARGET")

    def test_coverage_rejects_wrong_input_and_non_verbatim_evidence(self):
        extraction = ExtractionResult.model_validate({"units": [
            {"input_index": 9, "type": "fact", "subject": "fake", "content": "fake", "source_span": "数据库事务", "confidence": 0.9},
            {"input_index": 2, "type": "fact", "subject": "changed", "content": "changed", "source_span": "不存在的改写", "confidence": 0.9},
            {"input_index": 1, "type": "fact", "subject": "Java", "content": "List", "source_span": "Java List", "confidence": 0.9},
        ]})
        valid, missing = validate_extraction(extraction, [
            SourceInput(input_index=1, content="Java   List"),
            SourceInput(input_index=2, content="数据库事务具有原子性"),
        ])
        self.assertEqual([unit.subject for unit in valid.units], ["Java"])
        self.assertEqual(missing, [2])

    def test_planning_rejects_unknown_unit_reference(self):
        unit = PlanningUnit(
            ref="unit_001", input_index=1, type="fact", subject="Java",
            content="List", source_span="List", confidence=0.9,
        )
        proposal = MergeProposal(
            operation="CREATE_DOCUMENT", unit_refs=["unit_999"],
            target_document_id=None, target_title="Java", reason="new",
            before=None, after="# Java", evidence="List", confidence=0.9,
        )
        with self.assertRaises(AIProviderError) as caught:
            missing_proposal_refs([proposal], [unit])
        self.assertEqual(caught.exception.code, "AI_INVALID_UNIT_REF")

    def test_stream_chat_parses_sse_and_uses_safe_stream_options(self):
        captured = {}

        def handler(request):
            captured.update(json.loads(request.content))
            body = "\n".join([
                'data: {"choices":[{"delta":{"content":"GROUNDING: knowledge\\n"}}],"usage":null}',
                'data: {"choices":[{"delta":{"content":"答案 [S1]"}}],"usage":null}',
                'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":4}}',
                'data: [DONE]',
                '',
            ])
            return httpx.Response(200, request=request, text=body)

        ai = self.make_ai(handler)
        parts = list(ai.stream_chat(
            [{"role": "user", "content": "问题"}],
            [{"ref": "S1", "title": "文档", "excerpt": "答案"}],
            memory_block="<user_preferences />",
        ))
        self.assertEqual("".join(parts), "GROUNDING: knowledge\n答案 [S1]")
        self.assertIs(captured["stream"], True)
        self.assertEqual(captured["stream_options"], {"include_usage": True})
        self.assertIs(captured["enable_thinking"], False)
        self.assertIn("REFERENCE_MATERIAL", captured["messages"][1]["content"])
        self.assertNotIn("response_format", captured)

    def test_stream_chat_maps_upstream_and_invalid_chunk_errors(self):
        limited = self.make_ai(lambda request: httpx.Response(
            429, request=request, json={"error": {"code": "Throttling", "message": "slow"}},
        ))
        with self.assertRaises(AIProviderError) as caught:
            list(limited.stream_chat([{"role": "user", "content": "q"}], []))
        self.assertEqual(caught.exception.code, "AI_RATE_LIMITED")

        invalid = self.make_ai(lambda request: httpx.Response(
            200, request=request, text="data: not-json\n\n",
        ))
        with self.assertRaises(AIProviderError) as caught:
            list(invalid.stream_chat([{"role": "user", "content": "q"}], []))
        self.assertEqual(caught.exception.code, "AI_INVALID_RESPONSE")


class BailianOCRTest(unittest.TestCase):
    def make_ocr(self, handler):
        fake_settings = SimpleNamespace(
            validate=lambda: None,
            dashscope_base_url="https://example.test",
            ocr_model="test-ocr-model",
            **{"dashscope_api" + "_key": "test-value"},
        )
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch("app.ai.settings", fake_settings):
            return BailianOCR(client=client)

    def test_recognize_sends_image_and_returns_usage(self):
        captured = {}

        def handler(request):
            captured.update(json.loads(request.content))
            return httpx.Response(200, request=request, json={
                "choices": [{"message": {"content": "# 标题\n\n识别结果"}}],
                "usage": {
                    "prompt_tokens": 33,
                    "completion_tokens": 9,
                    "prompt_tokens_details": {"image_tokens": 21},
                },
            })

        ocr = self.make_ocr(handler)
        result = ocr.recognize(
            "data:image/png;base64,AAAA", source_id="src_test", sequence=2,
        )

        self.assertEqual(captured["model"], "test-ocr-model")
        image_part = captured["messages"][0]["content"][0]
        self.assertEqual(image_part["image_url"]["url"], "data:image/png;base64,AAAA")
        self.assertEqual(result.text, "# 标题\n\n识别结果")
        self.assertEqual(result.image_tokens, 21)

    def test_rate_limit_is_stable_reupload_error(self):
        ocr = self.make_ocr(lambda request: httpx.Response(
            429, request=request, json={"error": {"code": "Throttling", "message": "slow down"}},
        ))
        with self.assertRaises(AIProviderError) as caught:
            ocr.recognize("data:image/png;base64,AAAA", source_id="src_test", sequence=1)
        self.assertEqual(caught.exception.code, "OCR_RATE_LIMITED")
        self.assertFalse(caught.exception.retryable)

    def test_empty_response_is_stable_reupload_error(self):
        ocr = self.make_ocr(lambda request: httpx.Response(200, request=request, json={
            "choices": [{"message": {"content": "  "}}],
        }))
        with self.assertRaises(AIProviderError) as caught:
            ocr.recognize("data:image/png;base64,AAAA", source_id="src_test", sequence=1)
        self.assertEqual(caught.exception.code, "OCR_INVALID_RESPONSE")
        self.assertFalse(caught.exception.retryable)


if __name__ == "__main__":
    unittest.main()
