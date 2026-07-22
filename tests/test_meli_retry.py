"""Testes da retentativa/backoff do cliente Mercado Livre (rate limit 429 e 5xx)."""

import httpx

from app import meli


def _resp(status: int, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, headers=headers or {}, request=httpx.Request("GET", "http://x"))


# --- Cálculo do tempo de espera ------------------------------------------------


def test_retry_after_usa_cabecalho():
    assert meli._retry_after(_resp(429, {"Retry-After": "5"}), 0) == 5.0


def test_retry_after_cabecalho_invalido_cai_no_backoff():
    r = _resp(429, {"Retry-After": "abc"})
    assert meli._retry_after(r, 0) == meli._BACKOFF_BASE
    assert meli._retry_after(r, 2) == meli._BACKOFF_BASE * 4


def test_retry_after_sem_cabecalho_backoff_exponencial():
    r = _resp(503)
    assert meli._retry_after(r, 0) == meli._BACKOFF_BASE
    assert meli._retry_after(r, 1) == meli._BACKOFF_BASE * 2


# --- Laço de retentativa -------------------------------------------------------


def test_request_retenta_no_429_e_sucede(monkeypatch):
    chamadas = {"n": 0}
    esperas: list[float] = []

    def fake_request(method, url, **kwargs):
        chamadas["n"] += 1
        return _resp(200) if chamadas["n"] >= 3 else _resp(429, {"Retry-After": "0"})

    monkeypatch.setattr(meli.httpx, "request", fake_request)
    monkeypatch.setattr(meli, "_sleep", lambda s: esperas.append(s))

    resp = meli._request("GET", "http://x")
    assert resp.status_code == 200
    assert chamadas["n"] == 3
    assert len(esperas) == 2  # dormiu antes de cada retentativa


def test_request_retenta_em_5xx(monkeypatch):
    chamadas = {"n": 0}

    def fake_request(method, url, **kwargs):
        chamadas["n"] += 1
        return _resp(200) if chamadas["n"] >= 2 else _resp(502)

    monkeypatch.setattr(meli.httpx, "request", fake_request)
    monkeypatch.setattr(meli, "_sleep", lambda s: None)

    assert meli._request("GET", "http://x").status_code == 200
    assert chamadas["n"] == 2


def test_request_desiste_apos_max_tentativas(monkeypatch):
    chamadas = {"n": 0}

    def fake_request(method, url, **kwargs):
        chamadas["n"] += 1
        return _resp(429, {"Retry-After": "0"})

    monkeypatch.setattr(meli.httpx, "request", fake_request)
    monkeypatch.setattr(meli, "_sleep", lambda s: None)

    resp = meli._request("GET", "http://x")
    assert resp.status_code == 429
    assert chamadas["n"] == meli._MAX_RETRIES + 1


def test_request_nao_retenta_em_erro_de_cliente(monkeypatch):
    chamadas = {"n": 0}

    def fake_request(method, url, **kwargs):
        chamadas["n"] += 1
        return _resp(400)

    monkeypatch.setattr(meli.httpx, "request", fake_request)
    monkeypatch.setattr(meli, "_sleep", lambda s: None)

    assert meli._request("GET", "http://x").status_code == 400
    assert chamadas["n"] == 1
