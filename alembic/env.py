import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import get_database_url  # noqa: E402
from backend.models import Base  # noqa: E402

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    # allow programmatic override (tests): config.set_main_option("sqlalchemy.url", ...)
    explicit = config.attributes.get("url") or os.environ.get("DATABASE_URL")
    return explicit or get_database_url()


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _url()
    if url.startswith("sqlite") and ":memory:" not in url and "///" in url:
        Path(url.split("///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
