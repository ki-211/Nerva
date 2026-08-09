import os
import subprocess
import sys
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.dialects.postgresql import ARRAY


PROJECT_ROOT = Path(__file__).resolve().parents[3]


@unittest.skipUnless(os.getenv("NERVA_TEST_POSTGRES_URL"), "requires a dedicated NERVA_TEST_POSTGRES_URL")
class PostgreSQLMigrationIntegrationTest(unittest.TestCase):
    """Destructive only to an explicitly named test database; never uses DATABASE_URL."""

    @classmethod
    def setUpClass(cls):
        cls.database_url = os.environ["NERVA_TEST_POSTGRES_URL"]
        parsed = make_url(cls.database_url)
        if parsed.get_backend_name() != "postgresql" or "test" not in (parsed.database or "").lower():
            raise unittest.SkipTest("NERVA_TEST_POSTGRES_URL must point to a PostgreSQL database containing 'test' in its name")

    def alembic(self, *arguments: str) -> None:
        environment = os.environ.copy()
        environment["DATABASE_URL"] = self.database_url
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *arguments], cwd=PROJECT_ROOT,
            env=environment, capture_output=True, text=True, encoding="utf-8", timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_array_and_0010_0011_0012_migrations(self):
        self.alembic("downgrade", "base")
        self.alembic("upgrade", "0009")
        self.alembic("upgrade", "0010")
        self.alembic("upgrade", "0011")
        self.alembic("upgrade", "0012")

        engine = create_engine(self.database_url)
        try:
            inspector = inspect(engine)
            embedding = next(column for column in inspector.get_columns("document_chunks") if column["name"] == "embedding")
            self.assertIsInstance(embedding["type"], ARRAY)
            self.assertIn("audit_events", inspector.get_table_names())
            with engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one(), "0012")
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
