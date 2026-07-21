"""Testes da camada de persistência (SQLite)."""

import time

from app import database


def test_token_crud(temp_db):
    assert database.get_token() is None
    database.save_token(1, "AT", "RT", "read", 3600)
    tok = database.get_token()
    assert tok["access_token"] == "AT"
    assert tok["refresh_token"] == "RT"
    database.clear_tokens()
    assert database.get_token() is None


def test_user_crud(temp_db):
    assert database.has_user() is False
    uid = database.create_user("joao", "hash", "salt")
    assert uid > 0
    assert database.has_user() is True
    assert database.get_user()["username"] == "joao"
    assert database.get_user_by_username("joao")["id"] == uid
    assert database.get_user_by_username("inexistente") is None


def test_config_crud(temp_db):
    assert database.get_config("x") is None
    database.set_config("x", "1")
    assert database.get_config("x") == "1"
    database.set_config("x", "2")  # upsert
    assert database.get_config("x") == "2"


def test_quick_replies(temp_db):
    database.add_quick_reply("Oi", "Olá, tudo bem?")
    replies = database.list_quick_replies()
    assert len(replies) == 1
    rid = replies[0]["id"]
    database.delete_quick_reply(rid)
    assert database.list_quick_replies() == []


def test_snapshots(temp_db):
    database.save_snapshot("2026-07-20", {"vendas": 3, "faturamento": 100.0})
    database.save_snapshot("2026-07-20", {"vendas": 5, "faturamento": 200.0})  # upsert
    snaps = database.list_snapshots()
    assert len(snaps) == 1
    assert snaps[0]["vendas"] == 5


def test_scheduled_tasks(temp_db):
    agora = int(time.time())
    database.add_task("pausar", "MLB1", agora - 10, "Titulo")
    database.add_task("preco", "MLB2", agora + 3600, "Outro", 99.9)
    tasks = database.list_tasks()
    assert len(tasks) == 2
    vencidas = database.due_tasks(agora)
    assert len(vencidas) == 1
    tid = vencidas[0]["id"]
    database.finish_task(tid, "concluida", "ok")
    assert database.due_tasks(agora) == []
    # cancelar só afeta pendentes
    pendente = [t for t in database.list_tasks() if t["status"] == "pendente"][0]
    database.cancel_task(pendente["id"])
    cancelada = [t for t in database.list_tasks() if t["id"] == pendente["id"]][0]
    assert cancelada["status"] == "cancelada"


def test_cache(temp_db):
    assert database.cache_get("k") is None
    ts = database.cache_set("k", '{"a": 1}')
    assert isinstance(ts, int)
    row = database.cache_get("k")
    assert row["valor"] == '{"a": 1}'
    database.cache_delete("k")
    assert database.cache_get("k") is None
