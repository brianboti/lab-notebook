import logging
import sys

from alembic import context

from app import db
from app.models import Base

# Plain lines on stdout: the migration job's log shows each step without a logging config file.
logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


def run_migrations_online() -> None:
    with db.engine().connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not used; run `alembic upgrade head` against a database.")
run_migrations_online()
