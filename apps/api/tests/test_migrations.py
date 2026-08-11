import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.store import metadata
from app.main import EXPECTED_DATABASE_REVISION


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class MigrationBootstrapTest(unittest.TestCase):
    def run_alembic(self, database_url: str, *arguments: str) -> str:
        env = os.environ.copy()
        env["DATABASE_URL"] = database_url
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        self.assertEqual(
            result.returncode, 0,
            msg=f"alembic {' '.join(arguments)} failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        return result.stdout + result.stderr

    def test_empty_database_reaches_head_and_hybrid_migration_round_trips(self):
        with tempfile.TemporaryDirectory(prefix="nerva-migration-test-") as tempdir:
            database_path = Path(tempdir) / "empty.db"
            database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"

            self.run_alembic(database_url, "upgrade", "head")
            self.assertEqual(EXPECTED_DATABASE_REVISION, "0016")
            self.assertIn(f"{EXPECTED_DATABASE_REVISION} (head)", self.run_alembic(database_url, "current"))
            self.assertIn(
                "No new upgrade operations detected",
                self.run_alembic(database_url, "check"),
            )

            engine = create_engine(database_url)
            try:
                inspector = inspect(engine)
                self.assertEqual(set(metadata.tables), set(inspector.get_table_names()) - {"alembic_version"})
                self.assertIn(
                    "idx_chat_sessions_user_updated",
                    {item["name"] for item in inspector.get_indexes("chat_sessions")},
                )
                self.assertIn(
                    "idx_chat_messages_session_created",
                    {item["name"] for item in inspector.get_indexes("chat_messages")},
                )
                self.assertIn(
                    "idx_document_chunks_user_status",
                    {item["name"] for item in inspector.get_indexes("document_chunks")},
                )
                self.assertIn("audit_events", inspector.get_table_names())
                self.assertIn("research_sessions", inspector.get_table_names())
                self.assertIn("research_messages", inspector.get_table_names())
                self.assertIn("knowledge_hub_settings", inspector.get_table_names())
                self.assertIn("long_term_memories", inspector.get_table_names())
                self.assertIn("long_term_memory_mutations", inspector.get_table_names())
                self.assertIn("long_term_memory_events", inspector.get_table_names())
                self.assertIn(
                    "memory_refs", {column["name"] for column in inspector.get_columns("chat_messages")},
                )
                self.assertIn(
                    "long_term_memory_enabled",
                    {column["name"] for column in inspector.get_columns("knowledge_hub_settings")},
                )
            finally:
                engine.dispose()

            self.run_alembic(database_url, "downgrade", "0009")
            engine = create_engine(database_url)
            try:
                self.assertNotIn("document_chunks", set(inspect(engine).get_table_names()))
            finally:
                engine.dispose()

            self.run_alembic(database_url, "downgrade", "0008")
            engine = create_engine(database_url)
            try:
                tables = set(inspect(engine).get_table_names())
                self.assertNotIn("chat_sessions", tables)
                self.assertNotIn("chat_messages", tables)
            finally:
                engine.dispose()

            self.run_alembic(database_url, "upgrade", "head")
            self.assertIn(
                "No new upgrade operations detected",
                self.run_alembic(database_url, "check"),
            )


if __name__ == "__main__":
    unittest.main()
