"""Testes de rotas com dados (cobrem os corpos de laço e ramos com registros)."""

from app import main, meli
from tests.conftest import ITEM

# --- OAuth callback ------------------------------------------------------------


def test_callback_sucesso(auth_client, monkeypatch):
    monkeypatch.setattr(main.secrets, "token_urlsafe", lambda n=24: "FIXEDSTATE")
    # /conectar grava oauth_state e pkce_verifier na sessão.
    auth_client.get("/mercadolivre/conectar", follow_redirects=False)
    r = auth_client.get("/callback?code=abc&state=FIXEDSTATE", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"


def test_callback_erro_de_autorizacao(auth_client):
    r = auth_client.get("/callback?error=access_denied", follow_redirects=False)
    assert r.status_code == 303


def test_callback_state_invalido(auth_client):
    r = auth_client.get("/callback?code=x&state=errado", follow_redirects=False)
    assert r.status_code == 303


# --- Concorrência com catálogo -------------------------------------------------


def test_concorrencia_com_catalogo(auth_client, monkeypatch):
    item = dict(ITEM)
    item["catalog_product_id"] = "CAT1"
    item["price"] = 150.0
    monkeypatch.setattr(meli, "get_item", lambda iid: item)
    monkeypatch.setattr(
        meli,
        "get_catalog_competitors",
        lambda pid: [{"id": "Z", "price": 100.0}, {"id": "Y", "price": 120.0}],
    )
    r = auth_client.get("/anuncios/MLB1/concorrencia", follow_redirects=False)
    assert r.status_code == 200
    assert "150" in r.text or "100" in r.text


# --- Tendências por texto livre ------------------------------------------------


def test_tendencias_por_termo(auth_client):
    r = auth_client.get("/tendencias?termo=camiseta", follow_redirects=False)
    assert r.status_code == 200


# --- Telas com registros -------------------------------------------------------


def _order(oid="OID1"):
    return {
        "id": oid,
        "date_created": "2026-07-20T10:00:00.000-00:00",
        "total_amount": 200.0,
        "status": "paid",
        "buyer": {"id": 9, "nickname": "Comprador"},
        "order_items": [{"item": {"title": "Produto vendido"}, "quantity": 2, "sale_fee": 20.0}],
        "shipping": {"id": 555},
    }


def test_vendas_com_pedido(auth_client, monkeypatch):
    monkeypatch.setattr(meli, "list_all_orders", lambda *a, **k: [_order()])
    r = auth_client.get("/vendas", follow_redirects=False)
    assert r.status_code == 200
    assert "OID1" in r.text


def test_vendas_exportar_com_pedido(auth_client, monkeypatch):
    monkeypatch.setattr(meli, "list_all_orders", lambda *a, **k: [_order()])
    r = auth_client.get("/vendas/exportar", follow_redirects=False)
    assert r.status_code == 200
    assert "vendas.csv" in r.headers.get("content-disposition", "")


def test_vendas_busca_e_filtro(auth_client, monkeypatch):
    monkeypatch.setattr(meli, "list_all_orders", lambda *a, **k: [_order()])
    r = auth_client.get("/vendas?q=comprador&status=paid", follow_redirects=False)
    assert r.status_code == 200


def test_lucratividade_com_pedido(auth_client, monkeypatch):
    monkeypatch.setattr(meli, "search_orders", lambda *a, **k: [_order()])
    r = auth_client.get("/lucratividade", follow_redirects=False)
    assert r.status_code == 200
    r2 = auth_client.get("/lucratividade/exportar", follow_redirects=False)
    assert r2.status_code == 200


def test_estatisticas_com_visitas(auth_client, monkeypatch):
    monkeypatch.setattr(meli, "get_item_visits", lambda iid: {"MLB1": 100})
    r = auth_client.get("/estatisticas", follow_redirects=False)
    assert r.status_code == 200


def test_pos_venda_com_perguntas(auth_client, monkeypatch):
    monkeypatch.setattr(
        meli,
        "search_questions",
        lambda *a, **k: {"total": 1, "questions": [{"id": 1, "text": "Qual o frete?"}]},
    )
    monkeypatch.setattr(
        meli,
        "search_claims",
        lambda *a, **k: {"data": [{"id": "c1", "status": "opened"}]},
    )
    r = auth_client.get("/pos-venda", follow_redirects=False)
    assert r.status_code == 200


def test_mensagens_com_conteudo(auth_client, monkeypatch):
    monkeypatch.setattr(
        meli,
        "get_order",
        lambda oid: {"id": oid, "pack_id": "PACK1", "buyer": {"id": 9}, "order_items": []},
    )
    monkeypatch.setattr(
        meli,
        "get_pack_messages",
        lambda *a, **k: {
            "messages": [
                {
                    "text": "Oi",
                    "from": {"user_id": 9},
                    "message_date": {"created": "2026-07-20T10:00:00.000-00:00"},
                }
            ]
        },
    )
    r = auth_client.get("/vendas/OID1/mensagens", follow_redirects=False)
    assert r.status_code == 200


def test_promocoes_com_campanhas(auth_client, monkeypatch):
    monkeypatch.setattr(
        meli,
        "get_seller_promotions",
        lambda uid: [{"id": "P1", "name": "Promo", "type": "DEAL", "status": "started"}],
    )
    monkeypatch.setattr(
        meli,
        "get_item_promotions",
        lambda iid: [{"id": "P1", "type": "DEAL", "offer_price": 80}],
    )
    r = auth_client.get("/promocoes", follow_redirects=False)
    assert r.status_code == 200
    r2 = auth_client.get("/promocoes/MLB1", follow_redirects=False)
    assert r2.status_code == 200


def test_anuncios_busca_status(auth_client):
    r = auth_client.get("/anuncios?q=produto&status=active", follow_redirects=False)
    assert r.status_code == 200


def test_home_atualizar(auth_client):
    r = auth_client.get("/?atualizar=1", follow_redirects=False)
    assert r.status_code == 200
