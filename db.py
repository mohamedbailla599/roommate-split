"""Database access layer for roommate-split supporting SQLite and Neon PostgreSQL."""

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent
SCHEMA_SQLITE_PATH = BASE_DIR / "schema.sql"
SCHEMA_PG_PATH = BASE_DIR / "schema_pg.sql"


class PgRow(dict):
    """Row object that supports both dictionary key access and integer index access."""
    def __init__(self, cols: List[str], values: tuple):
        super().__init__(zip(cols, values))
        self._values = values

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class PgCursorWrapper:
    """Cursor wrapper translating SQLite parameter markers (?) to PostgreSQL (%s)."""
    def __init__(self, raw_cursor: Any):
        self._cursor = raw_cursor
        self.lastrowid: Optional[int] = None

    def execute(self, query: str, params: Optional[Any] = None) -> "PgCursorWrapper":
        clean_q = query.strip()
        if clean_q.upper().startswith("PRAGMA"):
            return self

        # Convert SQLite ? placeholders to PostgreSQL %s
        clean_q = clean_q.replace("?", "%s")

        # Automatically append RETURNING id for INSERT statements on tables with an id primary key
        is_insert = clean_q.strip().upper().startswith("INSERT INTO")
        should_return_id = (
            is_insert 
            and "RETURNING" not in clean_q.upper() 
            and "expense_participants" not in clean_q.lower()
        )
        if should_return_id:
            clean_q = clean_q.rstrip("; ") + " RETURNING id;"

        if params is not None:
            self._cursor.execute(clean_q, params)
        else:
            self._cursor.execute(clean_q)

        if should_return_id:
            try:
                row = self._cursor.fetchone()
                if row:
                    self.lastrowid = row[0]
            except Exception:
                self.lastrowid = None
        else:
            self.lastrowid = None
        return self

    def fetchone(self) -> Optional[PgRow]:
        r = self._cursor.fetchone()
        if r is None:
            return None
        cols = [desc[0] for desc in self._cursor.description]
        return PgRow(cols, r)

    def fetchall(self) -> List[PgRow]:
        rows = self._cursor.fetchall()
        if not rows:
            return []
        cols = [desc[0] for desc in self._cursor.description]
        return [PgRow(cols, r) for r in rows]

    def close(self) -> None:
        self._cursor.close()


class PgConnectionWrapper:
    """Connection wrapper ensuring full parity with sqlite3 Connection interface."""
    def __init__(self, raw_conn: Any, pool: Optional[Any] = None):
        self._conn = raw_conn
        self._pool = pool

    def cursor(self) -> PgCursorWrapper:
        if self._conn is None:
            raise RuntimeError("Cannot use cursor on a closed connection.")
        return PgCursorWrapper(self._conn.cursor())

    def execute(self, query: str, params: Optional[Any] = None) -> PgCursorWrapper:
        try:
            cur = self.cursor()
            cur.execute(query, params)
            return cur
        except Exception as e:
            err_msg = str(e).lower()
            if ("closed" in err_msg or "terminating connection" in err_msg) and self._pool is not None:
                try:
                    # Stale connection recovery
                    try:
                        self._pool.putconn(self._conn, close=True)
                    except Exception:
                        pass
                    self._conn = self._pool.getconn()
                    cur = self.cursor()
                    cur.execute(query, params)
                    return cur
                except Exception:
                    raise e
            raise

    def commit(self) -> None:
        if self._conn is not None:
            self._conn.commit()

    def rollback(self) -> None:
        if self._conn is not None:
            self._conn.rollback()

    def close(self) -> None:
        if self._pool is not None and self._conn is not None:
            try:
                self._conn.rollback()
            except Exception:
                pass
            try:
                self._pool.putconn(self._conn)
            except Exception:
                pass
            self._conn = None
            self._pool = None
        elif self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "PgConnectionWrapper":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()


_pg_pools: Dict[str, Any] = {}
_pg_pools_lock = threading.Lock()


def _get_or_create_pool(target: str) -> Any:
    global _pg_pools
    if target not in _pg_pools:
        with _pg_pools_lock:
            if target not in _pg_pools:
                from psycopg2.pool import ThreadedConnectionPool
                _pg_pools[target] = ThreadedConnectionPool(
                    minconn=1,
                    maxconn=10,
                    dsn=target
                )
    return _pg_pools[target]


def close_all_pools() -> None:
    global _pg_pools
    with _pg_pools_lock:
        for p in _pg_pools.values():
            try:
                p.closeall()
            except Exception:
                pass
        _pg_pools.clear()


def is_postgres_url(url: Optional[str]) -> bool:
    if not url:
        return False
    return url.startswith("postgresql://") or url.startswith("postgres://")


def get_default_target() -> str:
    # If DATABASE_PATH is explicitly set (e.g. during pytest suite runs), honor it
    db_path = os.environ.get("DATABASE_PATH")
    if db_path and not is_postgres_url(db_path):
        return db_path

    pg_url = os.environ.get("DATABASE_URL")
    if is_postgres_url(pg_url):
        return pg_url

    return db_path or str(BASE_DIR / "expenses.db")


def get_connection(db_target: Optional[str] = None) -> Any:
    target = db_target or get_default_target()

    if is_postgres_url(target):
        # Clean channel_binding if present since standard psycopg2 driver might not need it
        clean_target = target.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        pool = _get_or_create_pool(clean_target)
        for _ in range(3):
            try:
                raw_conn = pool.getconn()
                if raw_conn.closed:
                    pool.putconn(raw_conn, close=True)
                    continue
                # Pre-ping to discard connections terminated by Neon serverless idle timeout
                with raw_conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                return PgConnectionWrapper(raw_conn, pool=pool)
            except Exception:
                try:
                    pool.putconn(raw_conn, close=True)
                except Exception:
                    pass

        # Fallback to direct fresh connection if pool connections were stale
        import psycopg2
        raw_conn = psycopg2.connect(clean_target)
        return PgConnectionWrapper(raw_conn)

    # SQLite
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_target: Optional[str] = None) -> None:
    target = db_target or get_default_target()

    if is_postgres_url(target):
        conn = get_connection(target)
        with open(SCHEMA_PG_PATH, "r", encoding="utf-8") as f:
            ddl = f.read()
        cur = conn._conn.cursor()
        cur.execute(ddl)
        conn.commit()
        # Ensure avatar_url column exists for existing tables
        try:
            cur.execute("ALTER TABLE roommates ADD COLUMN IF NOT EXISTS avatar_url TEXT;")
            conn.commit()
        except Exception:
            conn.rollback()
        conn.close()
    else:
        conn = get_connection(target)
        with open(SCHEMA_SQLITE_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
        # Ensure avatar_url column exists for existing SQLite tables
        try:
            conn.execute("ALTER TABLE roommates ADD COLUMN avatar_url TEXT;")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        conn.close()
