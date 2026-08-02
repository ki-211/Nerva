from sqlalchemy import text

from app.settings import settings
from app.store import Store


store = Store(settings.sqlalchemy_url())
with store.engine.connect() as connection:
    row = connection.execute(
        text("SELECT current_database(), current_user, version()")
    ).one()

print(f"Database: {row[0]}")
print(f"User: {row[1]}")
print(f"Server: {row[2]}")
print("Nerva PostgreSQL connection is ready.")

