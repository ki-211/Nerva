import tempfile
import unittest
from pathlib import Path

from app.ai import LocalDemoAI
from app.store import Store


class KnowledgeFlowTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = (Path(self.tempdir.name) / "test.db").as_posix()
        self.store = Store(f"sqlite+pysqlite:///{db_path}")
        self.ai = LocalDemoAI()

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def test_create_then_merge_and_log(self):
        first = "FastAPI Middleware 在路由之前执行，可用于日志与鉴权。"
        proposal = self.ai.propose(first, "FastAPI Middleware", [])
        change_set = self.store.create_change_set("text", first, "FastAPI Middleware", proposal)
        self.store.apply_change_set(change_set["id"], None)

        documents = self.store.list_documents()
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["version"], 1)

        second = "FastAPI Middleware 也可以统一添加请求 ID。"
        proposal = self.ai.propose(second, "FastAPI Middleware", documents)
        self.assertEqual(proposal.operation, "ADD_BLOCK")
        change_set = self.store.create_change_set("text", second, "FastAPI Middleware", proposal)
        self.store.apply_change_set(change_set["id"], None)

        documents = self.store.list_documents()
        self.assertEqual(documents[0]["version"], 2)
        self.assertIn("请求 ID", documents[0]["markdown"])
        self.assertEqual(len(self.store.list_events()), 2)


if __name__ == "__main__":
    unittest.main()
