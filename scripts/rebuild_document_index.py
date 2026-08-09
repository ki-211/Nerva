"""One-shot idempotent rebuild of current document chunk indexes.

Run from the repository root after applying Alembic 0010.
"""
from app.ai import get_ai_adapter
from app.retrieval import rebuild_document_index
from app.settings import settings
from app.store import Store


def main() -> None:
    store = Store(settings.sqlalchemy_url(), create_schema=False)
    provider = get_ai_adapter()
    try:
        with store.engine.connect() as db:
            from app.store import documents
            rows = db.execute(documents.select()).mappings().all()
        for document in rows:
            rebuild_document_index(store, document["user_id"], document["id"], provider)
    finally:
        store.close()


if __name__ == "__main__":
    main()
