"""Testes de segurança: proteção CSRF e páginas de erro."""

import asyncio

from starlette.exceptions import HTTPException
from starlette.requests import Request

from app import main


def _fake_request(path="/"):
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "query_string": b"",
        "session": {},
    }
    return Request(scope)


# --- CSRF ----------------------------------------------------------------------


def test_csrf_bloqueia_origem_externa(client):
    r = client.post(
        "/entrar",
        data={"username": "x", "password": "y"},
        headers={"Origin": "http://evil.com"},
        follow_redirects=False,
    )
    assert r.status_code == 403
    assert "CSRF" in r.text


def test_csrf_permite_mesma_origem(client):
    # Sem Origin/Referer (mesma origem no TestClient) a requisição passa.
    r = client.post(
        "/entrar",
        data={"username": "x", "password": "y"},
        follow_redirects=False,
    )
    assert r.status_code != 403


# --- Páginas de erro -----------------------------------------------------------


def test_pagina_404_com_marca(client):
    r = client.get("/rota-que-nao-existe", follow_redirects=False)
    assert r.status_code == 404
    assert "Erro 404" in r.text
    assert "Voltar ao painel" in r.text


def test_metodo_nao_permitido_texto_simples(client):
    # POST em rota só-GET -> 405 tratado pelo handler (ramo "demais erros").
    r = client.post("/", follow_redirects=False)
    assert r.status_code == 405


def test_pagina_erro_direta(temp_db):
    resp = main._pagina_erro(
        _fake_request(),
        codigo=500,
        titulo="Algo deu errado",
        mensagem="m",
        detalhe="d",
        icone="!",
        status=500,
    )
    assert resp.status_code == 500


def test_handler_http_500(temp_db):
    exc = HTTPException(status_code=503)
    resp = asyncio.run(main._erro_http(_fake_request(), exc))
    assert resp.status_code == 503


def test_handler_interno(temp_db):
    resp = asyncio.run(main._erro_interno(_fake_request(), RuntimeError("boom")))
    assert resp.status_code == 500
