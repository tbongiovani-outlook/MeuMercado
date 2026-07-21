"""Fixtures compartilhadas: banco temporário, cliente HTTP e mocks do Mercado Livre."""

import pytest
from fastapi.testclient import TestClient

from app import auth, database, main, meli
from app.config import settings

# Dados de teste reutilizáveis --------------------------------------------------

USER = {
    "id": 13177531,
    "nickname": "TESTER",
    "seller_reputation": {"level_id": "5_green"},
}

ITEM = {
    "id": "MLB1",
    "title": "Produto de teste completo do anuncio ML",
    "price": 100.0,
    "available_quantity": 5,
    "sold_quantity": 2,
    "status": "active",
    "permalink": "https://mercadolivre.com/MLB1",
    "thumbnail": "http://x/t.jpg",
    "pictures": [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}],
    "catalog_product_id": None,
    "category_id": "MLB1234",
    "listing_type_id": "gold_special",
    "shipping": {"free_shipping": True},
    "attributes": [],
}


def mock_meli(monkeypatch):
    """Substitui todas as funções do cliente Mercado Livre por respostas seguras."""
    defaults = {
        "is_configured": lambda: True,
        "api_get": lambda path, params=None: dict(USER),
        "get_me": lambda: dict(USER),
        "get_client_id": lambda: "cid-teste",
        "get_client_secret": lambda: "secret-teste",
        "get_redirect_uri": lambda: "https://x/callback.html",
        "list_item_ids": lambda uid, limit=50: ["MLB1"],
        "list_all_item_ids": lambda uid, cap=200: ["MLB1"],
        "get_items_details": lambda ids: [dict(ITEM)],
        "search_orders": lambda *a, **k: [],
        "list_all_orders": lambda *a, **k: [],
        "search_questions": lambda *a, **k: {"total": 0, "questions": []},
        "search_claims": lambda *a, **k: {"paging": {"total": 0}, "data": []},
        "get_catalog_competitors": lambda pid: [],
        "get_item": lambda iid: dict(ITEM),
        "get_item_description": lambda iid: (
            "Descricao de teste com bem mais de quarenta caracteres para pontuar."
        ),
        "get_category_attributes": lambda cid: [],
        "get_category_name": lambda cid: "Categoria Teste",
        "get_trends": lambda cid="": [],
        "get_seller_promotions": lambda uid: [],
        "get_item_promotions": lambda iid: [],
        "get_item_visits": lambda iid: {iid: 0},
        "get_order": lambda oid: {"id": oid, "order_items": [], "buyer": {"id": 9}},
        "get_shipment": lambda sid: {"status": "shipped", "substatus": None},
        "get_pack_messages": lambda *a, **k: {"messages": []},
        "get_price_suggestion": lambda iid: {},
        "predict_category": lambda t: {"category_id": "MLB1234", "category_name": "Cat"},
        "generate_pkce_pair": lambda: ("verifier", "challenge"),
        "build_authorization_url": lambda state, challenge: "https://auth.ml/x",
        "exchange_code": lambda code, verifier: None,
        "publish": lambda **k: {
            "item": {"id": "MLBNEW", "title": "novo"},
            "catalog_product": None,
        },
        "upload_picture": lambda *a, **k: "picid",
        "update_item": lambda iid, payload: {},
        "update_item_status": lambda iid, status: {},
        "update_item_description": lambda iid, text: {},
        "duplicate_item": lambda iid: {"id": "MLBDUP"},
        "apply_item_promotion": lambda *a, **k: {},
        "remove_item_promotion": lambda *a, **k: {},
        "answer_question": lambda qid, text: {},
        "send_pack_message": lambda *a, **k: {},
    }
    for name, fn in defaults.items():
        monkeypatch.setattr(meli, name, fn, raising=False)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Aponta o banco para um arquivo temporário isolado por teste."""
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(settings, "database_path", str(db_file))
    database.init_db()
    return db_file


@pytest.fixture
def client(temp_db):
    """Cliente HTTP sem autenticação (não dispara o lifespan/agendador)."""
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture
def mocked_meli(monkeypatch):
    mock_meli(monkeypatch)
    return meli


@pytest.fixture
def auth_client(temp_db, monkeypatch):
    """Cliente autenticado, com conta ML conectada e API mockada."""
    mock_meli(monkeypatch)
    salt, password_hash = auth.hash_password("senha123")
    database.create_user("tester", password_hash, salt)
    database.save_token(USER["id"], "APP_USR-x", "TG-x", "read write", 21600)
    c = TestClient(main.app, raise_server_exceptions=False)
    resp = c.post(
        "/entrar",
        data={"username": "tester", "password": "senha123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    return c
