"""Testes do ranking de produtos (ordenação, visitas em lote e rota)."""

from app import main, meli


def test_ordenar_ranking_por_vendidos():
    produtos = [{"sold": 1}, {"sold": 5}, {"sold": 3}]
    ordenados = main._ordenar_ranking(produtos, "vendidos")
    assert [p["sold"] for p in ordenados] == [5, 3, 1]


def test_ordenar_ranking_conversao_none_por_ultimo():
    produtos = [{"conversao": None}, {"conversao": 10.0}, {"conversao": 2.0}]
    ordenados = main._ordenar_ranking(produtos, "conversao")
    assert ordenados[0]["conversao"] == 10.0
    assert ordenados[-1]["conversao"] is None


def test_get_items_visits_lista(monkeypatch):
    monkeypatch.setattr(
        meli,
        "api_get",
        lambda path, params=None: [
            {"item_id": "MLB1", "total_visits": 42},
            {"item_id": "MLB2", "total_visits": 7},
        ],
    )
    assert meli.get_items_visits(["MLB1", "MLB2"]) == {"MLB1": 42, "MLB2": 7}


def test_get_items_visits_vazio():
    assert meli.get_items_visits([]) == {}


def test_get_items_visits_erro_tolerante(monkeypatch):
    def boom(path, params=None):
        raise RuntimeError("indisponível")

    monkeypatch.setattr(meli, "api_get", boom)
    assert meli.get_items_visits(["MLB1"]) == {}


def test_ranking_route_ok(auth_client, monkeypatch):
    monkeypatch.setattr(meli, "get_items_visits", lambda ids: {"MLB1": 50})
    r = auth_client.get("/ranking")
    assert r.status_code == 200
    assert "Ranking de produtos" in r.text


def test_ranking_route_metrica_invalida_usa_padrao(auth_client, monkeypatch):
    monkeypatch.setattr(meli, "get_items_visits", lambda ids: {"MLB1": 10})
    r = auth_client.get("/ranking?por=xyz")
    assert r.status_code == 200
