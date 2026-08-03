import tempfile
import unittest
from pathlib import Path

from sqlalchemy import insert, select

from app.ai import LocalDemoAI
from app.store import LEGACY_USER_ID, Store, now_utc, sources, users


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

    def test_first_user_claims_legacy_data(self):
        with self.store.engine.begin() as db:
            db.execute(insert(users).values(
                id=LEGACY_USER_ID, email="legacy@nerva.invalid", display_name="Legacy",
                status="disabled", created_at=now_utc(), updated_at=now_utc(),
            ))
            db.execute(insert(sources).values(
                id="src_legacy", user_id=LEGACY_USER_ID, kind="text", title="Legacy",
                content="legacy content", created_at=now_utc(),
            ))
        claimed = self.store.create_user("claim@example.com", "Claim")
        with self.store.engine.connect() as db:
            owner = db.execute(select(sources.c.user_id).where(sources.c.id == "src_legacy")).scalar_one()
            legacy = db.execute(select(users.c.id).where(users.c.id == LEGACY_USER_ID)).first()
        self.assertEqual(owner, claimed["id"])
        self.assertIsNone(legacy)


if __name__ == "__main__":
    unittest.main()
