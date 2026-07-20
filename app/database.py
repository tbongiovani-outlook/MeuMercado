"""Camada de persistência (SQLite) para os tokens do Mercado Livre.

MVP single-user: guardamos o token mais recente. A tabela já usa `user_id`
como chave primária, então evoluir para multiusuário depois é simples.
"""

import sqlite3
import time
from contextlib import contextmanager
from typing import Optional

from .config import settings


@contextmanager
def get_conn():
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tokens (
                user_id       INTEGER PRIMARY KEY,
                access_token  TEXT NOT NULL,
                refresh_token TEXT,
                scope         TEXT,
                expires_at    INTEGER NOT NULL,
                updated_at    INTEGER NOT NULL
            )
            """
        )


def save_token(
    user_id: int,
    access_token: str,
    refresh_token: Optional[str],
    scope: Optional[str],
    expires_in: int,
) -> None:
    now = int(time.time())
    expires_at = now + int(expires_in)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO tokens (user_id, access_token, refresh_token, scope, expires_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                access_token=excluded.access_token,
                refresh_token=excluded.refresh_token,
                scope=excluded.scope,
                expires_at=excluded.expires_at,
                updated_at=excluded.updated_at
            """,
            (user_id, access_token, refresh_token, scope, expires_at, now),
        )


def get_token() -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM tokens ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def clear_tokens() -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM tokens")
