from contextlib import contextmanager

import psycopg
from pgvector.psycopg import register_vector

from .config import get_settings


@contextmanager
def get_conn():
    # Short-lived connection per use. Fine for the Phase 0 dev loop; swap for a
    # pool (psycopg_pool) once this runs under load in later phases.
    conn = psycopg.connect(get_settings().database_url, autocommit=True)
    try:
        register_vector(conn)
        yield conn
    finally:
        conn.close()
