"""Testes das funções utilitárias do módulo principal (lógica pura e de cache)."""

from datetime import UTC, datetime, timedelta

import pytest

from app import database, main, meli
from tests.conftest import mock_meli

# --- Comparação de tendência ---------------------------------------------------


def test_trend():
    assert main._trend(0, 0) == {"dir": "flat", "pct": None}
    assert main._trend(10, 0) == {"dir": "up", "pct": None}
    assert main._trend(20, 10) == {"dir": "up", "pct": 100}
    assert main._trend(5, 10) == {"dir": "down", "pct": -50}
    assert main._trend(10, 10) == {"dir": "flat", "pct": 0}


# --- Datas ---------------------------------------------------------------------


def test_order_dt():
    assert main._order_dt({}) is None
    assert main._order_dt({"date_created": "not-a-date"}) is None
    dt = main._order_dt({"date_created": "2026-07-20T10:00:00"})
    assert dt.year == 2026


def test_datetimebr():
    assert main._datetimebr(None) == "—"
    assert main._datetimebr(0) == "—"
    assert "/" in main._datetimebr(1_700_000_000)


# --- Busca em pedidos ----------------------------------------------------------


def test_order_bate():
    order = {
        "id": 123,
        "buyer": {"nickname": "Fulano"},
        "order_items": [{"item": {"title": "Camiseta Azul"}}],
    }
    assert main._order_bate(order, "123")
    assert main._order_bate(order, "fulano")
    assert main._order_bate(order, "camiseta")
    assert not main._order_bate(order, "inexistente")


# --- Métricas de pedidos -------------------------------------------------------


def test_orders_metrics():
    agora = datetime(2026, 7, 21, tzinfo=UTC)
    orders = [
        {
            "date_created": (agora - timedelta(days=1)).isoformat(),
            "total_amount": 100,
            "order_items": [{"sale_fee": 10}],
        },
        {
            "date_created": (agora - timedelta(days=40)).isoformat(),
            "total_amount": 50,
            "order_items": [{"sale_fee": 5}],
        },
    ]
    m = main._orders_metrics(orders, agora)
    assert m["vendas_30d"] == 1
    assert m["faturamento_30d"] == 100.0
    assert m["comissoes_30d"] == 10.0
    assert m["liquido_30d"] == 90.0
    assert m["ticket_medio"] == 100.0
    assert len(m["vendas_por_dia"]) == 30


def test_destaques_ativos():
    assert main._destaques_ativos([]) == (None, None)
    detalhes = [
        {"status": "active", "sold_quantity": 5, "id": "A"},
        {"status": "active", "sold_quantity": 1, "id": "B"},
        {"status": "paused", "sold_quantity": 99, "id": "C"},
    ]
    mais, menos = main._destaques_ativos(detalhes)
    assert mais["id"] == "A"
    assert menos["id"] == "B"


# --- Payload de edição em massa ------------------------------------------------


def test_payload_massa(monkeypatch):
    monkeypatch.setattr(meli, "get_item", lambda iid: {"price": 100.0})
    assert main._payload_massa("estoque", 7, "MLB1") == {"available_quantity": 7}
    assert main._payload_massa("preco", 12.5, "MLB1") == {"price": 12.5}
    assert main._payload_massa("aumentar", 10, "MLB1") == {"price": 110.0}
    assert main._payload_massa("reduzir", 10, "MLB1") == {"price": 90.0}
    with pytest.raises(ValueError):
        main._payload_massa("desconhecida", 1, "MLB1")


# --- Concorrência --------------------------------------------------------------


def test_count_acima_concorrencia(monkeypatch):
    detalhes = [
        {"status": "active", "catalog_product_id": "CAT1", "price": 150.0, "id": "A"},
    ]
    monkeypatch.setattr(
        meli,
        "get_catalog_competitors",
        lambda pid: [{"id": "Z", "price": 100.0}],
    )
    assert main._count_acima_concorrencia(detalhes) == 1
    # Sem candidatos de catálogo -> 0
    assert main._count_acima_concorrencia([{"status": "active", "price": 10}]) == 0


def test_recomendacao_da_sugestao():
    assert main._recomendacao_da_sugestao(None, 10) is None
    assert main._recomendacao_da_sugestao({}, 10) is None
    rec = main._recomendacao_da_sugestao({"suggested_price": {"amount": 80}}, 100)
    assert rec["valor"] == 80.0
    # Preço igual -> sem recomendação
    assert main._recomendacao_da_sugestao({"suggested_price": {"amount": 100}}, 100) is None


# --- Sugestão de resposta ------------------------------------------------------


def test_sugerir_resposta():
    respostas = [
        {"titulo": "Frete", "texto": "O frete é grátis para todo o Brasil."},
        {"titulo": "Garantia", "texto": "Garantia de 90 dias."},
    ]
    sugestao = main._sugerir_resposta("Qual o valor do frete?", respostas)
    assert "frete" in sugestao.lower()
    assert main._sugerir_resposta("", respostas) == ""
    assert main._sugerir_resposta("xyz", []) == ""


def test_tokens_remove_stopwords():
    toks = main._tokens("Olá, qual é o prazo de entrega?")
    assert "prazo" in toks
    assert "entrega" in toks
    assert "qual" not in toks  # stopword


# --- Cache ---------------------------------------------------------------------


def test_cache_ler_gravar(temp_db):
    ts = main._cache_gravar("chave", {"a": 1})
    assert isinstance(ts, int)
    dados, quando = main._cache_ler("chave")
    assert dados == {"a": 1}
    assert quando == ts
    # force ignora o cache
    assert main._cache_ler("chave", force=True) is None
    # chave inexistente
    assert main._cache_ler("nao-existe") is None


def test_cache_ttl_expira(temp_db, monkeypatch):
    database.set_config("cache_ttl_min", "0")  # expira imediatamente
    main._cache_gravar("k", {"v": 1})
    assert main._cache_ler("k") is None


def test_limite_estoque_baixo(temp_db):
    assert main._limite_estoque_baixo() == 3
    database.set_config("estoque_baixo", "7")
    assert main._limite_estoque_baixo() == 7
    database.set_config("estoque_baixo", "abc")  # inválido -> padrão
    assert main._limite_estoque_baixo() == 3


def test_nav_badges(temp_db):
    assert main._nav_badges() == {"perguntas": 0, "vendas": 0}
    main._cache_gravar("nav_badges", {"perguntas": 4, "vendas": 2})
    assert main._nav_badges() == {"perguntas": 4, "vendas": 2}


def test_invalidar_cache_itens(temp_db, monkeypatch):
    mock_meli(monkeypatch)
    main._cache_gravar("anuncios:13177531", [1])
    main._cache_gravar("promocoes:13177531", [1])
    main._invalidar_cache_itens()
    assert database.cache_get("anuncios:13177531") is None
    assert database.cache_get("promocoes:13177531") is None


# --- Execução de tarefas agendadas ---------------------------------------------


def test_executar_tarefa(monkeypatch):
    chamadas = {}
    monkeypatch.setattr(
        meli, "update_item_status", lambda iid, status: chamadas.update(status=status)
    )
    monkeypatch.setattr(meli, "update_item", lambda iid, payload: chamadas.update(payload=payload))
    main._executar_tarefa({"tipo": "pausar", "item_id": "MLB1", "valor": None})
    assert chamadas["status"] == "paused"
    main._executar_tarefa({"tipo": "preco", "item_id": "MLB1", "valor": 50})
    assert chamadas["payload"] == {"price": 50.0}
    with pytest.raises(ValueError):
        main._executar_tarefa({"tipo": "xpto", "item_id": "MLB1", "valor": None})


def test_run_due_tasks(temp_db, monkeypatch):
    import time

    monkeypatch.setattr(meli, "update_item_status", lambda iid, status: None)
    database.add_task("pausar", "MLB1", int(time.time()) - 5, "Titulo")
    main._run_due_tasks()
    assert database.due_tasks(int(time.time())) == []
