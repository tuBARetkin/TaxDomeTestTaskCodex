"""Explicit transaction and isolation settings for plain-SQL repositories."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine


PAYMENT_ISOLATION_LEVEL = "READ COMMITTED"


@contextmanager
def transaction(engine: Engine) -> Iterator[Connection]:
    with engine.connect() as connection:
        connection.execution_options(isolation_level=PAYMENT_ISOLATION_LEVEL)
        with connection.begin():
            yield connection
