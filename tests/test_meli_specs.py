"""Testes do grounding de descrição: specs reais do catálogo do Mercado Livre."""

from app import meli


def test_get_product_specs_retorna_atributos_reais(monkeypatch):
    monkeypatch.setattr(
        meli,
        "search_catalog_products",
        lambda q, limit=5: [{"id": "MLB1", "name": "Apple iPhone 16 Pro Max 512GB"}],
    )
    monkeypatch.setattr(
        meli,
        "get_catalog_product",
        lambda pid: {
            "attributes": [
                {"id": "BRAND", "name": "Marca", "value_name": "Apple"},
                {"id": "INTERNAL_MEMORY", "name": "Memória interna", "value_name": "512 GB"},
                {"id": "ITEM_CONDITION", "name": "Condição", "value_name": "Novo"},
                {"id": "X", "name": "Vazio", "value_name": ""},
            ]
        },
    )
    specs = meli.get_product_specs("iPhone 16 Pro Max 512GB")
    assert "- Marca: Apple" in specs
    assert "- Memória interna: 512 GB" in specs
    assert "Condição" not in specs  # ITEM_CONDITION é ignorado
    assert "Vazio" not in specs  # sem value_name é pulado


def test_get_product_specs_sem_match_retorna_vazio(monkeypatch):
    monkeypatch.setattr(
        meli,
        "search_catalog_products",
        lambda q, limit=5: [{"id": "MLB1", "name": "Geladeira Brastemp Frost Free"}],
    )
    assert meli.get_product_specs("iPhone 16 Pro Max 512GB") == ""


def test_get_product_specs_erro_retorna_vazio(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("sem token")

    monkeypatch.setattr(meli, "search_catalog_products", boom)
    assert meli.get_product_specs("qualquer coisa") == ""


def test_get_product_specs_titulo_vazio():
    assert meli.get_product_specs("") == ""


def test_get_product_specs_by_id_retorna_atributos(monkeypatch):
    monkeypatch.setattr(
        meli,
        "get_catalog_product",
        lambda pid: {
            "attributes": [
                {"id": "BRAND", "name": "Marca", "value_name": "Apple"},
                {"id": "PROCESSOR", "name": "Processador", "value_name": "Apple A18 Pro"},
                {"id": "GTIN", "name": "GTIN", "value_name": "123"},
            ]
        },
    )
    specs = meli.get_product_specs_by_id("MLB123")
    assert "- Marca: Apple" in specs
    assert "- Processador: Apple A18 Pro" in specs
    assert "GTIN" not in specs  # ignorado


def test_get_product_specs_by_id_vazio_ou_erro(monkeypatch):
    assert meli.get_product_specs_by_id("") == ""

    def boom(pid):
        raise RuntimeError("404")

    monkeypatch.setattr(meli, "get_catalog_product", boom)
    assert meli.get_product_specs_by_id("MLB123") == ""
