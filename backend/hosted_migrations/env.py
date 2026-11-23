"""The hosted schema has its own revision history, including on a shared SQLite fixture."""

from alembic import context
from services.hosted_database import hosted_database_url, hosted_engine

url = hosted_database_url()
if url is None:
    raise RuntimeError("VOICE_API_DATABASE_URL is required for hosted migrations")

options = {"version_table": "hosted_alembic_version"}

if context.is_offline_mode():
    context.configure(url=url, literal_binds=True, **options)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = hosted_engine(url)
    try:
        with engine.begin() as connection:
            if (
                connection.dialect.name == "sqlite"
                and not connection.connection.driver_connection.in_transaction
            ):
                # Python's legacy SQLite transaction mode skips BEGIN before DDL.
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            context.configure(connection=connection, **options)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
