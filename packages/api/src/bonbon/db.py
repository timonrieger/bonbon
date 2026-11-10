"""PostgreSQL access (RDS), see docs/architecture.md#data-model and docs/decisions/0006.

One connection per Lambda container, opened on first use and reused across invocations.
The sum of reserved concurrency of all functions that use the database must stay well below
the instance's max_connections (79 on db.t4g.micro), see template.yaml.
"""

import os
import ssl
from collections.abc import Generator
from contextlib import contextmanager, suppress
from functools import cache
from pathlib import Path

from pg8000.exceptions import InterfaceError
from pg8000.native import Connection

# Public RDS CA bundle (https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem).
# With it, TLS verifies both the certificate chain and the hostname of the database.
CA_BUNDLE = Path(__file__).parent / "certs" / "global-bundle.pem"


def connect(user: str, password: str) -> Connection:
    """Open a new TLS connection to the stack's database."""
    return Connection(
        user=user,
        password=password,
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        database=os.environ["DB_NAME"],
        ssl_context=ssl.create_default_context(cafile=CA_BUNDLE),
        timeout=5,
        application_name=os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "bonbon"),
    )


@cache
def connection() -> Connection:
    """The container's connection, as the user in DB_USER / DB_PASSWORD."""
    return connect(os.environ["DB_USER"], os.environ["DB_PASSWORD"])


def reset() -> None:
    """Drop the cached connection, e.g. after the database restarted. The next call reconnects."""
    if connection.cache_info().currsize:
        with suppress(InterfaceError, OSError):
            connection().close()
    connection.cache_clear()


def query(sql: str, **params: object) -> list[list]:
    """Run one read-only statement with :named parameters and return its rows.

    If the cached connection turns out to be broken (e.g. the database was stopped and
    started), reconnect once and retry. Safe only because the statement doesn't write;
    use transaction() for writes.
    """
    try:
        return connection().run(sql, **params)
    except InterfaceError:
        reset()
        return connection().run(sql, **params)


@contextmanager
def transaction() -> Generator[Connection]:
    """Run the block in one transaction: commit at the end, roll back on any error."""
    conn = connection()
    try:
        conn.run("START TRANSACTION")
        try:
            yield conn
        except BaseException:
            conn.run("ROLLBACK")
            raise
        conn.run("COMMIT")
    except InterfaceError:
        # The socket is gone (database restarted, idle timeout). Fail this request and
        # reconnect on the next one; retrying here could apply a write twice.
        reset()
        raise
