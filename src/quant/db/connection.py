"""PostgreSQL connection manager for the quant database."""

import psycopg2
from psycopg2.extensions import connection as PgConnection

from quant.config import get_settings


def get_dsn() -> str:
    """Return the configured PostgreSQL DSN."""
    return get_settings().pg_dsn


def get_connection(dsn: str | None = None, autocommit: bool = False) -> PgConnection:
    """Open a PostgreSQL connection using the configured DSN by default."""
    conn = psycopg2.connect(dsn or get_dsn())
    conn.autocommit = autocommit
    return conn
