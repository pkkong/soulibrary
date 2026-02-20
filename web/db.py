import os
from urllib.parse import urlparse

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except Exception:
    psycopg2 = None
    RealDictCursor = None


def using_postgres():
    return bool(os.environ.get("DATABASE_URL") or os.environ.get("DB_HOST"))


def _parse_database_url(url):
    parsed = urlparse(url)
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "dbname": parsed.path.lstrip("/") if parsed.path else "",
        "user": parsed.username,
        "password": parsed.password,
    }


def _convert_placeholders(sql):
    # SQLite uses "?" while psycopg2 uses "%s".
    return sql.replace("?", "%s")


class PgConn:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        cur = self._conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(_convert_placeholders(sql), params or [])
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def get_db(_sqlite_path=None):
    if not using_postgres():
        raise RuntimeError("PostgreSQL env vars are required (DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD).")
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required for PostgreSQL connections.")
    url = os.environ.get("DATABASE_URL")
    if url:
        cfg = _parse_database_url(url)
    else:
        cfg = {
            "host": os.environ.get("DB_HOST"),
            "port": int(os.environ.get("DB_PORT", "5432")),
            "dbname": os.environ.get("DB_NAME", "postgres"),
            "user": os.environ.get("DB_USER", "root"),
            "password": os.environ.get("DB_PASSWORD", ""),
        }
    conn = psycopg2.connect(**cfg)
    return PgConn(conn)
