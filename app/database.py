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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quick_replies (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo     TEXT NOT NULL,
                texto      TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_snapshots (
                dia         TEXT PRIMARY KEY,
                vendas      INTEGER,
                faturamento REAL,
                liquido     REAL,
                ativos      INTEGER,
                sem_estoque INTEGER,
                perguntas   INTEGER,
                reclamacoes INTEGER,
                created_at  INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo        TEXT NOT NULL,
                item_id     TEXT NOT NULL,
                titulo      TEXT,
                valor       REAL,
                executar_em INTEGER NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pendente',
                resultado   TEXT,
                created_at  INTEGER NOT NULL
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


def list_quick_replies() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, titulo, texto FROM quick_replies ORDER BY titulo"
        ).fetchall()
        return [dict(r) for r in rows]


def add_quick_reply(titulo: str, texto: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO quick_replies (titulo, texto, created_at) VALUES (?, ?, ?)",
            (titulo, texto, int(time.time())),
        )


def delete_quick_reply(reply_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM quick_replies WHERE id = ?", (reply_id,))


def save_snapshot(dia: str, dados: dict) -> None:
    """Grava (ou atualiza) o resumo diário de métricas do painel."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO daily_snapshots
                (dia, vendas, faturamento, liquido, ativos, sem_estoque,
                 perguntas, reclamacoes, created_at)
            VALUES (:dia, :vendas, :faturamento, :liquido, :ativos, :sem_estoque,
                    :perguntas, :reclamacoes, :created_at)
            ON CONFLICT(dia) DO UPDATE SET
                vendas = excluded.vendas,
                faturamento = excluded.faturamento,
                liquido = excluded.liquido,
                ativos = excluded.ativos,
                sem_estoque = excluded.sem_estoque,
                perguntas = excluded.perguntas,
                reclamacoes = excluded.reclamacoes,
                created_at = excluded.created_at
            """,
            {
                "dia": dia,
                "vendas": int(dados.get("vendas", 0)),
                "faturamento": float(dados.get("faturamento", 0.0)),
                "liquido": float(dados.get("liquido", 0.0)),
                "ativos": int(dados.get("ativos", 0)),
                "sem_estoque": int(dados.get("sem_estoque", 0)),
                "perguntas": int(dados.get("perguntas", 0)),
                "reclamacoes": int(dados.get("reclamacoes", 0)),
                "created_at": int(time.time()),
            },
        )


def list_snapshots(limit: int = 60) -> list[dict]:
    """Retorna os snapshots diários mais recentes (ordem cronológica)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM daily_snapshots ORDER BY dia DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def add_task(tipo: str, item_id: str, executar_em: int,
             titulo: str = "", valor: float | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO scheduled_tasks
                (tipo, item_id, titulo, valor, executar_em, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pendente', ?)
            """,
            (tipo, item_id, titulo, valor, executar_em, int(time.time())),
        )


def list_tasks(limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM scheduled_tasks ORDER BY executar_em DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def due_tasks(agora: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM scheduled_tasks WHERE status = 'pendente' AND executar_em <= ?",
            (agora,),
        ).fetchall()
        return [dict(r) for r in rows]


def finish_task(task_id: int, status: str, resultado: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE scheduled_tasks SET status = ?, resultado = ? WHERE id = ?",
            (status, resultado, task_id),
        )


def cancel_task(task_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE scheduled_tasks SET status = 'cancelada' WHERE id = ? AND status = 'pendente'",
            (task_id,),
        )
