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
