import os

from alembic import context
from sqlalchemy import create_engine

from stratagy.journal import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return (config.attributes.get("url") or os.environ.get("DATABASE_URL")
            or config.get_main_option("sqlalchemy.url"))


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _url()
    engine = create_engine(url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
