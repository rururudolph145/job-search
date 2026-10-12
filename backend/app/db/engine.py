import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

DEFAULT_DB_URL = "postgresql+psycopg://jobsearch:jobsearch@localhost:5432/jobsearch"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DB_URL)


def make_engine() -> Engine:
    return create_engine(database_url())


engine: Engine = make_engine()


@contextmanager
def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
