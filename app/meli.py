"""Cliente de integração com a API do Mercado Livre (OAuth 2.0 + chamadas REST)."""

import time
from urllib.parse import urlencode

import httpx

from . import database
from .config import settings

_TIMEOUT = 30
# Renova o token com esta antecedência (segundos) antes de expirar.
_REFRESH_MARGIN = 60


def get_client_id() -> str:
    return database.get_config("meli_client_id") or settings.meli_client_id


def get_client_secret() -> str:
    return database.get_config("meli_client_secret") or settings.meli_client_secret


def get_redirect_uri() -> str:
    return database.get_config("meli_redirect_uri") or settings.meli_redirect_uri


def is_configured() -> bool:
    return bool(get_client_id() and get_client_secret())


def build_authorization_url(state: str) -> str:
    """Monta a URL para redirecionar o vendedor ao consentimento do Mercado Livre."""
    params = {
        "response_type": "code",
        "client_id": get_client_id(),
        "redirect_uri": get_redirect_uri(),
        "state": state,
    }
    return f"{settings.meli_auth_domain}/authorization?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Troca o authorization code por um access token e persiste o resultado."""
    data = {
        "grant_type": "authorization_code",
        "client_id": get_client_id(),
        "client_secret": get_client_secret(),
        "code": code,
        "redirect_uri": get_redirect_uri(),
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
    resp.raise_for_status()
    return resp.json()


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
