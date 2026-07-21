"""Avaliação de qualidade e posicionamento de anúncios.

Calcula um índice (0–100) e uma checklist acionável com base nos principais
fatores que o Mercado Livre usa para posicionar (ranquear) anúncios:

- Fotos (quantidade e presença)          — muito relevante
- Frete grátis / Mercado Envios          — muito relevante
- Ficha técnica (atributos preenchidos)  — relevante
- Descrição do produto                   — relevante
- Tipo de anúncio (Clássico/Premium)     — relevante
- Título completo                        — relevante
- Estoque disponível                     — básico

Como a API `/items/{id}/health` não está disponível para anúncios comuns
(retorna 404 para `buying_mode = buy_it_now`), calculamos o índice localmente
a partir dos dados do próprio anúncio.
"""

from __future__ import annotations


def _foto_score(n: int) -> int:
    if n >= 6:
        return 25
    if n >= 3:
        return 18
    if n >= 1:
        return 8
    return 0


def _ficha_score(item: dict, category_attrs: list[dict]) -> tuple[int, int, int]:
    """Retorna (pontos, preenchidos, total) dos atributos importantes."""
    importantes = [
        a
        for a in category_attrs
        if (a.get("tags") or {}).get("required")
        or (a.get("tags") or {}).get("catalog_required")
    ]
    total = len(importantes)
    if total == 0:
        return 20, 0, 0

    preenchidos_ids = {
        a.get("id")
        for a in (item.get("attributes") or [])
        if a.get("value_id") or a.get("value_name")
    }
    preenchidos = sum(1 for a in importantes if a.get("id") in preenchidos_ids)
    pontos = round(20 * preenchidos / total)
    return pontos, preenchidos, total


def evaluate(item: dict, descricao: str, category_attrs: list[dict]) -> dict:
    """Avalia o anúncio e devolve índice + checklist."""
    checks: list[dict] = []
    score = 0

    # Fotos (25)
    n_fotos = len(item.get("pictures") or [])
    pts = _foto_score(n_fotos)
    score += pts
    checks.append(
        {
            "ok": n_fotos >= 3,
            "peso": "Alta",
            "titulo": f"Fotos ({n_fotos})",
            "dica": "Use no mínimo 3 fotos (ideal 6+), fundo branco, boa resolução "
            "e diferentes ângulos. Fotos aumentam a conversão e o posicionamento.",
        }
    )

    # Frete grátis (15)
    frete_gratis = bool((item.get("shipping") or {}).get("free_shipping"))
    score += 15 if frete_gratis else 0
    checks.append(
        {
            "ok": frete_gratis,
            "peso": "Alta",
            "titulo": "Frete grátis",
            "dica": "Oferecer frete grátis é um dos fatores que mais melhora a "
            "exposição do anúncio. Considere ativar, sobretudo com Mercado Envios Full.",
        }
    )

    # Ficha técnica (20)
    ficha_pts, preenchidos, total = _ficha_score(item, category_attrs)
    score += ficha_pts
    ficha_ok = total == 0 or preenchidos >= total
    checks.append(
        {
            "ok": ficha_ok,
            "peso": "Alta",
            "titulo": f"Ficha técnica ({preenchidos}/{total})"
            if total
            else "Ficha técnica",
            "dica": "Preencha todos os atributos obrigatórios e recomendados da "
            "categoria. Uma ficha completa melhora a busca e o posicionamento.",
        }
    )

    # Descrição (15)
    tem_descricao = len(descricao) >= 40
    score += 15 if tem_descricao else 0
    checks.append(
        {
            "ok": tem_descricao,
            "peso": "Média",
            "titulo": "Descrição do produto",
            "dica": "Escreva uma descrição clara e completa (benefícios, medidas, "
            "conteúdo da embalagem). Evite dados de contato — não é permitido.",
        }
    )

    # Tipo de anúncio (15)
    lt = item.get("listing_type_id")
    if lt in ("gold_pro", "gold_special"):
        tipo_pts, tipo_ok = 15, True
    elif lt == "gold":
        tipo_pts, tipo_ok = 8, False
    else:
        tipo_pts, tipo_ok = 0, False
    score += tipo_pts
    checks.append(
        {
            "ok": tipo_ok,
            "peso": "Alta",
            "titulo": "Tipo de anúncio",
            "dica": "Anúncios Clássico e Premium têm muito mais exposição que o "
            "Grátis. Para vender mais, considere o Clássico ou Premium.",
        }
    )

    # Título (10)
    titulo = item.get("title") or ""
    titulo_ok = len(titulo) >= 20
    score += 10 if titulo_ok else 4
    checks.append(
        {
            "ok": titulo_ok,
            "peso": "Média",
            "titulo": "Título completo",
            "dica": "Use um título descritivo com marca, modelo e características "
            "principais (até 60 caracteres). Evite repetição e palavras irrelevantes.",
        }
    )

    # Estoque (5)
    estoque = item.get("available_quantity") or 0
    estoque_ok = estoque > 0
    score += 5 if estoque_ok else 0
    checks.append(
        {
            "ok": estoque_ok,
            "peso": "Básica",
            "titulo": f"Estoque disponível ({estoque})",
            "dica": "Mantenha estoque disponível. Anúncios sem estoque perdem "
            "posição e podem ser pausados.",
        }
    )

    percent = max(0, min(100, score))
    if percent >= 80:
        nivel = "Ótimo"
    elif percent >= 55:
        nivel = "Bom"
    else:
        nivel = "A melhorar"

    return {"percent": percent, "nivel": nivel, "checks": checks}
