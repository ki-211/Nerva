import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.store import metadata


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

    def test_empty_database_reaches_head_and_chat_migration_round_trips(self):
        with tempfile.TemporaryDirectory(prefix="nerva-migration-test-") as tempdir:
            database_path = Path(tempdir) / "empty.db"
            database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"

            self.run_alembic(database_url, "upgrade", "head")
            self.assertIn("0009 (head)", self.run_alembic(database_url, "current"))
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
