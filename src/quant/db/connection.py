"""PostgreSQL connection manager for the quant database."""

import os
import psycopg2
import psycopg2.extras

DEFAULT_DSN = "host=localhost port=5432 dbname=quant_db user=quant password=quant123"


def get_dsn() -> str:
    return os.environ.get("QUANT_DB_DSN", DEFAULT_DSN)


def get_connection(dsn: str | None = None, autocommit: bool = False):
    conn = psycopg2.connect(dsn or get_dsn())
    conn.autocommit = autocommit
    return conn
