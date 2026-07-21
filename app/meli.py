"""Cliente de integração com a API do Mercado Livre (OAuth 2.0 + PKCE + REST)."""

import base64
import hashlib
import logging
import secrets
import time
from urllib.parse import urlencode

import httpx

from . import database
from .config import settings

_TIMEOUT = 30
# Renova o token com esta antecedência (segundos) antes de expirar.
_REFRESH_MARGIN = 60

_logger = logging.getLogger("meu_mercado.meli")


def generate_pkce_pair() -> tuple[str, str]:
    """Gera (code_verifier, code_challenge) para o fluxo PKCE (método S256)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def get_client_id() -> str:
    return database.get_config("meli_client_id") or settings.meli_client_id


def get_client_secret() -> str:
    return database.get_config("meli_client_secret") or settings.meli_client_secret


def get_redirect_uri() -> str:
    return database.get_config("meli_redirect_uri") or settings.meli_redirect_uri


def is_configured() -> bool:
    return bool(get_client_id() and get_client_secret())


def build_authorization_url(state: str, code_challenge: str) -> str:
    """Monta a URL para redirecionar o vendedor ao consentimento do Mercado Livre."""
    params = {
        "response_type": "code",
        "client_id": get_client_id(),
        "redirect_uri": get_redirect_uri(),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{settings.meli_auth_domain}/authorization?{urlencode(params)}"


def exchange_code(code: str, code_verifier: str) -> dict:
    """Troca o authorization code por um access token e persiste o resultado."""
    data = {
        "grant_type": "authorization_code",
        "client_id": get_client_id(),
        "client_secret": get_client_secret(),
        "code": code,
        "redirect_uri": get_redirect_uri(),
        "code_verifier": code_verifier,
    }
    token = _post_token(data)
    _persist(token)
    return token


def refresh_token(refresh: str) -> dict:
    """Usa o refresh token para obter um novo access token."""
    data = {
        "grant_type": "refresh_token",
        "client_id": get_client_id(),
        "client_secret": get_client_secret(),
        "refresh_token": refresh,
    }
    token = _post_token(data)
    _persist(token)
    return token


def get_valid_access_token() -> str | None:
    """Retorna um access token válido, renovando automaticamente se necessário."""
    token = database.get_token()
    if not token:
        return None
    if token["expires_at"] - time.time() < _REFRESH_MARGIN:
        if not token.get("refresh_token"):
            return None
        token = refresh_token(token["refresh_token"])
    return token["access_token"]


def api_get(path: str, params: dict | None = None) -> dict:
    """Faz um GET autenticado na API do Mercado Livre."""
    access = get_valid_access_token()
    if not access:
        raise RuntimeError("Sem token válido. Faça login novamente.")
    resp = httpx.get(
        f"{settings.meli_api_base}{path}",
        params=params,
        headers={"Authorization": f"Bearer {access}"},
        timeout=_TIMEOUT,
    )
    if resp.status_code >= 400:
        _logger.warning("GET %s -> %s", path, resp.status_code)
    resp.raise_for_status()
    return resp.json()


def api_post(path: str, payload: dict) -> dict:
    """Faz um POST autenticado (JSON) na API do Mercado Livre."""
    access = get_valid_access_token()
    if not access:
        raise RuntimeError("Sem token válido. Faça login novamente.")
    resp = httpx.post(
        f"{settings.meli_api_base}{path}",
        json=payload,
        headers={
            "Authorization": f"Bearer {access}",
            "Content-Type": "application/json",
        },
        timeout=_TIMEOUT,
    )
    if resp.status_code >= 400:
        _logger.warning("POST %s -> %s: %s", path, resp.status_code, resp.text[:400])
    resp.raise_for_status()
    return resp.json()


def api_put(path: str, payload: dict) -> dict:
    """Faz um PUT autenticado (JSON) na API do Mercado Livre."""
    access = get_valid_access_token()
    if not access:
        raise RuntimeError("Sem token válido. Faça login novamente.")
    resp = httpx.put(
        f"{settings.meli_api_base}{path}",
        json=payload,
        headers={
            "Authorization": f"Bearer {access}",
            "Content-Type": "application/json",
        },
        timeout=_TIMEOUT,
    )
    if resp.status_code >= 400:
        _logger.warning("PUT %s -> %s: %s", path, resp.status_code, resp.text[:400])
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Recursos de alto nível (anúncios, vendas, envios, pós-venda, etc.)
# ---------------------------------------------------------------------------

def get_me() -> dict:
    return api_get("/users/me")


def get_trends(category_id: str = "") -> list[dict]:
    """Termos de busca em alta no Mercado Livre (geral ou por categoria)."""
    path = f"/trends/MLB/{category_id}" if category_id else "/trends/MLB"
    data = api_get(path)
    return data if isinstance(data, list) else []


def update_item_status(item_id: str, status: str) -> dict:
    """Altera o status de um anúncio (active, paused ou closed)."""
    return api_put(f"/items/{item_id}", {"status": status})


def update_item(item_id: str, payload: dict) -> dict:
    """Atualiza campos de um anúncio (ex.: price, available_quantity)."""
    return api_put(f"/items/{item_id}", payload)


def answer_question(question_id: int, text: str) -> dict:
    """Responde a uma pergunta de um anúncio."""
    return api_post("/answers", {"question_id": question_id, "text": text})



def predict_category(title: str, site: str = "MLB") -> dict:
    """Sugere categoria e domínio a partir do título (domain discovery)."""
    results = api_get(
        f"/sites/{site}/domain_discovery/search", {"limit": 1, "q": title}
    )
    return results[0] if isinstance(results, list) and results else {}


def get_category_attributes(category_id: str) -> list[dict]:
    """Atributos de uma categoria (endpoint público, sem autenticação)."""
    resp = httpx.get(
        f"{settings.meli_api_base}/categories/{category_id}/attributes",
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _gtin_attributes(all_attrs: list[dict], gtin: str) -> list[dict]:
    """Resolve o(s) atributo(s) de GTIN: código informado ou motivo de vazio."""
    gtin_attr = next((a for a in all_attrs if a.get("id") == "GTIN"), None)
    if not gtin_attr or not (gtin_attr.get("tags") or {}).get("conditional_required"):
        return []
    if gtin.strip():
        return [{"id": "GTIN", "value_name": gtin.strip()}]

    reason = next((a for a in all_attrs if a.get("id") == "EMPTY_GTIN_REASON"), None)
    values = (reason or {}).get("values") or []
    chosen = next(
        (v for v in values if "não tem código" in v.get("name", "").lower()),
        values[-1] if values else None,
    )
    # Para publicar sem código de barras, o ML exige o atributo GTIN presente
    # (com valor nulo) + o motivo do GTIN vazio.
    result = [{"id": "GTIN", "value_name": None}]
    if chosen:
        result.append({"id": "EMPTY_GTIN_REASON", "value_id": chosen["id"]})
    return result


def build_required_attributes(category_id: str, brand: str, gtin: str = "") -> list[dict]:
    """Monta os atributos obrigatórios da categoria com valores razoáveis."""
    all_attrs = get_category_attributes(category_id)
    attrs: list[dict] = []

    for attr in all_attrs:
        if not (attr.get("tags") or {}).get("required"):
            continue
        attr_id = attr.get("id")
        allowed = attr.get("values") or []
        if attr_id == "BRAND":
            attrs.append({"id": "BRAND", "value_name": brand or "Genérica"})
        elif allowed:
            attrs.append({"id": attr_id, "value_id": allowed[0]["id"]})
        else:
            attrs.append({"id": attr_id, "value_name": brand or "Não especificado"})

    attrs.extend(_gtin_attributes(all_attrs, gtin))
    return attrs



def publish_item(payload: dict) -> dict:
    """Publica um novo anúncio (POST /items)."""
    return api_post("/items", payload)


def upload_picture(content: bytes, filename: str, content_type: str) -> str:
    """Envia uma imagem local para o Mercado Livre e retorna o id da foto."""
    access = get_valid_access_token()
    if not access:
        raise RuntimeError("Sem token válido. Faça login novamente.")
    resp = httpx.post(
        f"{settings.meli_api_base}/pictures/items/upload",
        headers={"Authorization": f"Bearer {access}"},
        files={"file": (filename, content, content_type or "image/jpeg")},
        timeout=_TIMEOUT,
    )
    if resp.status_code >= 400:
        _logger.warning("upload picture -> %s: %s", resp.status_code, resp.text[:400])
    resp.raise_for_status()
    return resp.json().get("id", "")


def publish_item_smart(base: dict, title: str) -> dict:
    """Publica tentando com 'title'; se a categoria exigir 'family_name', tenta assim."""
    try:
        return publish_item({**base, "title": title})
    except httpx.HTTPStatusError as exc:
        body = exc.response.text if exc.response is not None else ""
        if "family_name" in body:
            return publish_item({**base, "family_name": title})
        raise


def search_catalog_products(query: str, limit: int = 10) -> list[dict]:
    """Busca produtos no catálogo do Mercado Livre."""
    data = api_get(
        "/products/search",
        {"site_id": "MLB", "status": "active", "q": query, "limit": limit},
    )
    return data.get("results", [])


def get_catalog_competitors(product_id: str) -> list[dict]:
    """Lista as ofertas concorrentes de um produto de catálogo."""
    data = api_get(f"/products/{product_id}/items")
    return data.get("results", [])


def get_catalog_product(product_id: str) -> dict:
    """Detalhes de um produto de catálogo (inclui buy_box_winner)."""
    return api_get(f"/products/{product_id}")


def get_price_suggestion(item_id: str) -> dict:
    """Sugestão de preço competitivo do ML (vazio se não houver)."""
    try:
        return api_get(f"/suggestions/items/{item_id}/details")
    except Exception:  # noqa: BLE001
        return {}



def publish_catalog_item(
    catalog_product_id: str,
    price: float,
    quantity: int,
    listing_type_id: str,
    condition: str = "new",
    category_id: str = "",
) -> dict:
    """Publica um anúncio vinculado a um produto de catálogo existente."""
    payload = {
        "catalog_product_id": catalog_product_id,
        "catalog_listing": True,
        "price": price,
        "currency_id": "BRL",
        "available_quantity": quantity,
        "listing_type_id": listing_type_id,
        "condition": condition,
    }
    if category_id:
        payload["category_id"] = category_id
    return publish_item(payload)


def publish(
    *,
    title: str,
    category_id: str,
    price: float,
    available_quantity: int,
    condition: str,
    listing_type_id: str,
    brand: str = "",
    gtin: str = "",
    pictures: list[dict] | None = None,
) -> dict:
    """Publica um anúncio de forma resiliente.

    1) Tenta a publicação normal (com atributos obrigatórios da categoria);
    2) se a categoria exigir catálogo/GTIN, busca o produto no catálogo e
       publica vinculado a ele.

    Retorna ``{"item": <resposta>, "catalog_product": <produto|None>}``.
    """
    base = {
        "category_id": category_id,
        "price": price,
        "currency_id": "BRL",
        "available_quantity": available_quantity,
        "buying_mode": "buy_it_now",
        "condition": condition,
        "listing_type_id": listing_type_id,
        "attributes": build_required_attributes(category_id, brand, gtin),
    }
    if pictures:
        base["pictures"] = pictures

    try:
        return {"item": publish_item_smart(base, title.strip()), "catalog_product": None}
    except httpx.HTTPStatusError as exc:
        body = exc.response.text if exc.response is not None else ""
        needs_catalog = "GTIN" in body or "catalog" in body.lower()
        if not needs_catalog:
            raise
        produtos = search_catalog_products(title)
        if not produtos:
            raise
        escolhido = produtos[0]
        item = publish_catalog_item(
            escolhido["id"],
            price,
            available_quantity,
            listing_type_id,
            condition,
            category_id,
        )
        return {"item": item, "catalog_product": escolhido}


def get_item(item_id: str) -> dict:
    return api_get(f"/items/{item_id}")


def duplicate_item(item_id: str) -> dict:
    """Cria um novo anúncio a partir de um existente (cópia)."""
    src = get_item(item_id)
    payload = {
        "category_id": src.get("category_id"),
        "price": src.get("price"),
        "currency_id": src.get("currency_id") or "BRL",
        "available_quantity": src.get("available_quantity") or 1,
        "buying_mode": src.get("buying_mode") or "buy_it_now",
        "condition": src.get("condition") or "new",
        "listing_type_id": src.get("listing_type_id") or "gold_special",
    }
    pics = [{"id": p["id"]} for p in (src.get("pictures") or []) if p.get("id")]
    if pics:
        payload["pictures"] = pics

    catalog_id = src.get("catalog_product_id")
    if catalog_id and src.get("catalog_listing"):
        payload["catalog_product_id"] = catalog_id
        payload["catalog_listing"] = True
    else:
        payload["title"] = src.get("title", "")
        attrs = _copy_attributes(src.get("attributes") or [])
        if attrs:
            payload["attributes"] = attrs

    return api_post("/items", payload)


def _copy_attributes(attributes: list[dict]) -> list[dict]:
    """Extrai atributos reutilizáveis (com value_id ou value_name) para cópia."""
    copiados = []
    for attr in attributes:
        entry = {"id": attr.get("id")}
        if attr.get("value_id"):
            entry["value_id"] = attr["value_id"]
        elif attr.get("value_name"):
            entry["value_name"] = attr["value_name"]
        else:
            continue
        copiados.append(entry)
    return copiados


def get_item_description(item_id: str) -> str:
    """Retorna o texto da descrição do anúncio (vazio se não houver)."""
    try:
        data = api_get(f"/items/{item_id}/description")
    except Exception:  # noqa: BLE001
        return ""
    return (data.get("plain_text") or data.get("text") or "").strip()


def list_item_ids(user_id: int, limit: int = 50) -> list[str]:
    data = api_get(f"/users/{user_id}/items/search", {"limit": limit})
    return data.get("results", [])


def get_items_details(item_ids: list[str]) -> list[dict]:
    """Busca detalhes de vários itens de uma vez (multiget)."""
    if not item_ids:
        return []
    ids = ",".join(item_ids[:20])
    attrs = (
        "id,title,price,available_quantity,sold_quantity,status,"
        "permalink,thumbnail,catalog_product_id"
    )
    data = api_get("/items", {"ids": ids, "attributes": attrs})
    return [row.get("body", {}) for row in data if row.get("code") == 200]


def search_orders(seller_id: int, limit: int = 30, date_from: str = "") -> list[dict]:
    params = {"seller": seller_id, "sort": "date_desc", "limit": limit}
    if date_from:
        params["order.date_created.from"] = date_from
    data = api_get("/orders/search", params)
    return data.get("results", [])


def get_order(order_id: str) -> dict:
    return api_get(f"/orders/{order_id}")


def get_shipment(shipment_id: int) -> dict:
    return api_get(f"/shipments/{shipment_id}")


def search_questions(seller_id: int, status: str = "UNANSWERED") -> dict:
    """Perguntas recebidas nos anúncios do vendedor."""
    return api_get(
        "/questions/search",
        {"seller_id": seller_id, "status": status, "sort_fields": "date_created"},
    )


def get_pack_messages(pack_id: str, seller_id: int) -> dict:
    """Mensagens pós-venda de um pack/pedido."""
    return api_get(
        f"/messages/packs/{pack_id}/sellers/{seller_id}", {"tag": "post_sale"}
    )


def send_pack_message(pack_id: str, seller_id: int, buyer_id: int, text: str) -> dict:
    """Envia uma mensagem pós-venda ao comprador."""
    return api_post(
        f"/messages/packs/{pack_id}/sellers/{seller_id}?tag=post_sale",
        {
            "from": {"user_id": str(seller_id)},
            "to": {"user_id": str(buyer_id)},
            "text": text,
        },
    )


def search_claims(limit: int = 20, status: str = "opened") -> dict:
    """Reclamações do vendedor (pós-venda). Exige ao menos um filtro."""
    return api_get(
        "/post-purchase/v1/claims/search", {"status": status, "limit": limit}
    )


def get_item_visits(item_id: str) -> dict:
    return api_get("/visits/items", {"ids": item_id})


def get_billing_summary(user_id: int) -> dict:
    """Resumo de faturamento/comissões (saldo da conta)."""
    return api_get(f"/users/{user_id}/mercadopago_account/balance")


def _post_token(data: dict) -> dict:
    resp = httpx.post(
        f"{settings.meli_api_base}/oauth/token",
        data=data,
        headers={
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded",
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _persist(token: dict) -> None:
    database.save_token(
        user_id=token["user_id"],
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token"),
        scope=token.get("scope"),
        expires_in=token.get("expires_in", 21600),
    )
    _logger.info(
        "Token salvo (user_id=%s, expira em %ss).",
        token.get("user_id"),
        token.get("expires_in", 21600),
    )
