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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_user (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt          TEXT NOT NULL,
                created_at    INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_config (
                key   TEXT PRIMARY KEY,
                value TEXT
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


# --- Conta local do aplicativo (single-user) ---


def has_user() -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM app_user LIMIT 1").fetchone()
        return row is not None


def create_user(username: str, password_hash: str, salt: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO app_user (username, password_hash, salt, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (username, password_hash, salt, int(time.time())),
        )
        return int(cur.lastrowid)


def get_user() -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM app_user ORDER BY id LIMIT 1").fetchone()
        return dict(row) if row else None


def get_user_by_username(username: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM app_user WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row else None


# --- Configuração da aplicação (chave/valor) ---


def set_config(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO app_config (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def get_config(key: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM app_config WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None
