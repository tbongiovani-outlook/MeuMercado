"""Testes da avaliação de qualidade de anúncios (quality)."""

from app import quality


def _item(**over):
    base = {
        "pictures": [{"id": "1"}, {"id": "2"}, {"id": "3"}, {"id": "4"}, {"id": "5"}, {"id": "6"}],
        "shipping": {"free_shipping": True},
        "attributes": [],
        "listing_type_id": "gold_special",
        "title": "Produto completo com marca modelo e detalhes",
        "available_quantity": 10,
    }
    base.update(over)
    return base


def test_foto_score_faixas():
    assert quality._foto_score(6) == 25
    assert quality._foto_score(3) == 18
    assert quality._foto_score(1) == 8
    assert quality._foto_score(0) == 0


def test_ficha_score_sem_atributos_da_pontuacao_cheia():
    pts, preenchidos, total = quality._ficha_score({"attributes": []}, [])
    assert (pts, preenchidos, total) == (20, 0, 0)


def test_ficha_score_com_atributos_obrigatorios():
    attrs = [
        {"id": "BRAND", "tags": {"required": True}},
        {"id": "MODEL", "tags": {"catalog_required": True}},
    ]
    item = {"attributes": [{"id": "BRAND", "value_name": "Marca"}]}
    pts, preenchidos, total = quality._ficha_score(item, attrs)
    assert total == 2
    assert preenchidos == 1
    assert pts == 10


def test_evaluate_anuncio_otimo():
    resultado = quality.evaluate(_item(), "d" * 60, [])
    assert resultado["percent"] >= 80
    assert resultado["nivel"] == "Ótimo"
    assert len(resultado["checks"]) == 7


def test_evaluate_anuncio_fraco():
    item = _item(
        pictures=[], shipping={}, listing_type_id="free", title="curto", available_quantity=0
    )
    resultado = quality.evaluate(item, "", [])
    assert resultado["percent"] < 55
    assert resultado["nivel"] == "A melhorar"
    assert any(c["ok"] is False for c in resultado["checks"])
