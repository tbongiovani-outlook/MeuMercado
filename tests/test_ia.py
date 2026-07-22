"""Testes da integração de IA local (Ollama) e do endpoint /ia/sugerir."""

import httpx

from app import database, ia


def _boom(*_a, **_k):
    raise httpx.ConnectError("sem conexao")


# --- Configuração / helpers ----------------------------------------------------


def test_habilitada_desligada_por_padrao(temp_db):
    assert ia.habilitada() is False


def test_habilitada_e_defaults(temp_db):
    database.set_config("ia_habilitada", "1")
    assert ia.habilitada() is True
    assert ia.endpoint() == ia.DEFAULT_ENDPOINT
    assert ia.modelo() == ia.DEFAULT_MODELO


def test_endpoint_e_modelo_configuraveis(temp_db):
    database.set_config("ia_endpoint", "http://host:1234/")
    database.set_config("ia_modelo", "qwen2.5:3b")
    assert ia.endpoint() == "http://host:1234"  # sem barra final
    assert ia.modelo() == "qwen2.5:3b"


# --- disponivel() --------------------------------------------------------------


def test_disponivel_falsa_quando_desligada(temp_db):
    assert ia.disponivel() is False


def test_disponivel_verdadeira_quando_ollama_responde(temp_db, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(ia.httpx, "get", lambda *a, **k: httpx.Response(200))
    assert ia.disponivel() is True


def test_disponivel_falsa_quando_ollama_cai(temp_db, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(ia.httpx, "get", _boom)
    assert ia.disponivel() is False


# --- sugerir_resposta() --------------------------------------------------------


def test_sugerir_vazia_sem_pergunta_ou_desligada(temp_db):
    assert ia.sugerir_resposta("") == ""
    assert ia.sugerir_resposta("tem estoque?") == ""  # habilitada=False


def test_sugerir_sucesso(temp_db, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(
        ia.httpx,
        "post",
        lambda *a, **k: httpx.Response(
            200, json={"response": "  Sim, temos!  "}, request=httpx.Request("POST", "http://x")
        ),
    )
    assert ia.sugerir_resposta("tem estoque?", contexto="Camiseta") == "Sim, temos!"


def test_sugerir_falha_retorna_vazio(temp_db, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(ia.httpx, "post", _boom)
    assert ia.sugerir_resposta("tem estoque?") == ""


# --- Endpoint /ia/sugerir ------------------------------------------------------


def test_endpoint_401_sem_login(client):
    r = client.post("/ia/sugerir", data={"pergunta": "oi"}, follow_redirects=False)
    assert r.status_code == 401
    assert r.json()["ok"] is False


def test_endpoint_400_quando_ia_desligada(auth_client):
    r = auth_client.post("/ia/sugerir", data={"pergunta": "oi"})
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_endpoint_sucesso_com_ia(auth_client, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(ia, "sugerir_resposta", lambda *a, **k: "Resposta da IA")
    r = auth_client.post("/ia/sugerir", data={"pergunta": "tem estoque?"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["sugestao"] == "Resposta da IA"


def test_endpoint_fallback_para_heuristica(auth_client, monkeypatch):
    database.set_config("ia_habilitada", "1")
    database.add_quick_reply("Estoque", "Sim, temos em estoque!")
    monkeypatch.setattr(ia, "sugerir_resposta", lambda *a, **k: "")
    r = auth_client.post("/ia/sugerir", data={"pergunta": "voce tem estoque disponivel?"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "estoque" in body["sugestao"].lower()


def test_endpoint_sem_sugestao(auth_client, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(ia, "sugerir_resposta", lambda *a, **k: "")
    r = auth_client.post("/ia/sugerir", data={"pergunta": "xyzabc"})
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_configuracao_salva_campos_ia(auth_client):
    r = auth_client.post(
        "/configuracao",
        data={
            "client_id": "abc",
            "client_secret": "",
            "redirect_uri": "https://x/callback.html",
            "estoque_baixo": 3,
            "cache_ttl_min": 15,
            "ia_habilitada": "1",
            "ia_endpoint": "http://localhost:11434",
            "ia_modelo": "qwen2.5:3b",
        },
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert database.get_config("ia_habilitada") == "1"
    assert database.get_config("ia_modelo") == "qwen2.5:3b"


def test_configuracao_desliga_ia_por_padrao(auth_client):
    database.set_config("ia_habilitada", "1")
    # Checkbox desmarcado não envia o campo -> deve gravar "0".
    r = auth_client.post(
        "/configuracao",
        data={
            "client_id": "abc",
            "client_secret": "",
            "redirect_uri": "https://x/callback.html",
            "estoque_baixo": 3,
            "cache_ttl_min": 15,
        },
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert database.get_config("ia_habilitada") == "0"


# --- Página de Ajuda -----------------------------------------------------------


def test_ajuda_redireciona_sem_login(client):
    r = client.get("/ajuda", follow_redirects=False)
    assert r.status_code in (302, 303, 307)
    assert r.headers["location"] == "/entrar"


def test_ajuda_abre_logado(auth_client):
    r = auth_client.get("/ajuda")
    assert r.status_code == 200
    assert "Ollama" in r.text
    assert "IA local" in r.text


# --- Endpoint /ia/status -------------------------------------------------------


def test_ia_status_401_sem_login(client):
    r = client.get("/ia/status", follow_redirects=False)
    assert r.status_code == 401
    assert r.json()["ok"] is False


def test_ia_status_desligada(auth_client):
    r = auth_client.get("/ia/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["habilitada"] is False
    assert body["disponivel"] is False


def test_ia_status_ligada_e_disponivel(auth_client, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(ia, "disponivel", lambda *a, **k: True)
    r = auth_client.get("/ia/status")
    assert r.status_code == 200
    body = r.json()
    assert body["habilitada"] is True
    assert body["disponivel"] is True
    assert body["endpoint"] == ia.DEFAULT_ENDPOINT
    assert body["modelo"] == ia.DEFAULT_MODELO
