import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.auth import hash_password
from app.logging_config import scrub_sensitive
from app.store import Store


class ObservabilityApiTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        database = (Path(self.tempdir.name) / "observability.db").as_posix()
        self.store = Store(f"sqlite+pysqlite:///{database}")
        self.previous_store = main.store
        main.store = self.store
        self.store.ensure_admin(
            username=main.settings.admin_username,
            email=main.settings.admin_email,
            password_hash=hash_password(main.settings.admin_password),
        )
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def tearDown(self):
        self.client.close()
        main.store = self.previous_store
        self.store.close()
        self.tempdir.cleanup()

    def test_error_envelope_and_request_id_cover_404_and_validation(self):
        custom_id = "desktop-request-123"
        missing = self.client.get("/v1/does-not-exist", headers={"X-Request-ID": custom_id})
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.headers["X-Request-ID"], custom_id)
        self.assertEqual(missing.json()["error"]["request_id"], custom_id)
        self.assertEqual(missing.json()["error"]["code"], "NOT_FOUND")
        self.assertNotIn("detail", missing.json())

        invalid = self.client.post("/v1/auth/verification-codes", json={"email": "not-an-email"})
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json()["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(invalid.headers["X-Request-ID"], invalid.json()["error"]["request_id"])

    def test_health_and_metrics_are_machine_readable(self):
        live = self.client.get("/health/live")
        self.assertEqual(live.json()["status"], "live")
        metrics = self.client.get("/metrics")
        self.assertEqual(metrics.status_code, 200)
        self.assertIn("nerva_http_requests_total", metrics.text)
        self.assertIn("nerva_database_pool_utilization_ratio", metrics.text)

    def test_unhandled_exception_returns_safe_envelope(self):
        with patch.object(self.store, "count_chunks_by_status", side_effect=RuntimeError("password=secret")):
            response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "INTERNAL_ERROR")
        self.assertNotIn("password", response.text)
        self.assertEqual(response.headers["X-Request-ID"], response.json()["error"]["request_id"])

    def test_admin_login_is_audited_and_locked_by_account_and_ip(self):
        for _ in range(main.settings.admin_login_max_failures):
            failed = self.client.post("/v1/auth/admin-login", json={
                "username": main.settings.admin_username, "password": "definitely-wrong",
            })
            self.assertEqual(failed.status_code, 401)
        locked = self.client.post("/v1/auth/admin-login", json={
            "username": main.settings.admin_username, "password": main.settings.admin_password,
        })
        self.assertEqual(locked.status_code, 429)
        self.assertEqual(locked.json()["error"]["code"], "ADMIN_LOGIN_LOCKED")
        events = self.store.list_audit_events(action="admin.login")
        self.assertEqual(len([item for item in events if item["outcome"] == "failure"]), 10)
        self.assertEqual(events[-1]["outcome"], "locked")
        self.assertTrue(all("@" not in (item["target_id"] or "") for item in events))


class RedactionTest(unittest.TestCase):
    def test_sentry_and_log_payloads_remove_user_data_and_credentials(self):
        safe = scrub_sensitive({
            "request_id": "req-1", "markdown": "private document",
            "password": "secret", "nested": {
                "authorization": "Bearer abc.def", "message": "user@example.com token=plain",
            }, "request": {"data": "raw body", "query_string": "q=private"},
        })
        self.assertEqual(safe["request_id"], "req-1")
        self.assertEqual(safe["markdown"], "[Filtered]")
        self.assertEqual(safe["password"], "[Filtered]")
        self.assertEqual(safe["nested"]["authorization"], "[Filtered]")
        self.assertEqual(safe["request"]["data"], "[Filtered]")
        self.assertEqual(safe["request"]["query_string"], "[Filtered]")
        self.assertNotIn("user@example.com", safe["nested"]["message"])
        self.assertNotIn("token=plain", safe["nested"]["message"])

    def test_production_rejects_default_secrets_and_unsafe_runtime(self):
        insecure = replace(
            main.settings, environment="production", verification_code_secret="short",
            admin_password="admin", session_cookie_secure=False, log_format="text",
            metrics_token=None, sentry_dsn=None,
        )
        with self.assertRaises(RuntimeError):
            insecure.validate()


if __name__ == "__main__":
    unittest.main()
