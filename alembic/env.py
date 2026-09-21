from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from nano_banana.config import settings
from nano_banana.db.models import AdminAuditLog, Generation, User  # noqa: F401
from nano_banana.db.session import db_service

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = db_service.Base.metadata
config.set_main_option("sqlalchemy.url", db_service._get_safe_db_url())


def run_migrations_offline() -> None:
    url = db_service._get_safe_db_url()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        {"sqlalchemy.url": db_service._get_safe_db_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
