from sqlalchemy import text

from app.settings import settings
from app.store import Store


store = Store(settings.sqlalchemy_url(), create_schema=False)
with store.engine.connect() as connection:
    row = connection.execute(
        text("SELECT current_database(), current_user, version()")
    ).one()
    revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    ownership_columns = connection.execute(text("""
        SELECT COUNT(*) FROM information_schema.columns
        WHERE table_schema = current_schema() AND column_name = 'user_id'
          AND table_name IN ('sources', 'documents', 'document_versions',
                             'change_sets', 'change_items', 'knowledge_events')
    """)).scalar_one()

print(f"Database: {row[0]}")
print(f"User: {row[1]}")
print(f"Server: {row[2]}")
print(f"Schema revision: {revision}")
print(f"Owned knowledge tables: {ownership_columns}/6")
print("Nerva PostgreSQL connection is ready.")
