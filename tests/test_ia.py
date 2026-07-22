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


# --- gerar_descricao / sugerir_reclamacao / resumo_do_dia ----------------------


def _resp_ok(texto):
    return lambda *a, **k: httpx.Response(
        200, json={"response": texto}, request=httpx.Request("POST", "http://x")
    )


def test_gerar_descricao_sucesso(temp_db, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(ia.httpx, "post", _resp_ok("  Descrição top  "))
    assert ia.gerar_descricao("Camiseta", marca="Nike") == "Descrição top"


def test_gerar_descricao_remove_eco_instrucao(temp_db, monkeypatch):
    database.set_config("ia_habilitada", "1")
    vazado = (
        "2 a 3 parágrafos curtos e persuasivos destacando benefícios e usos do "
        "produto: Aproveite a água. Especificações técnicas: - Marca: Minalba"
    )
    monkeypatch.setattr(ia.httpx, "post", _resp_ok(vazado))
    saida = ia.gerar_descricao("Água Mineral")
    assert saida.startswith("Aproveite a água.")
    assert "parágrafos" not in saida


def test_descricao_ajustada_preserva_texto_limpo():
    limpo = "Água mineral ótima. Especificações técnicas: - Marca: Minalba"
    assert ia._descricao_ajustada(limpo) == limpo


def test_gerar_descricao_injeta_specs_no_prompt(temp_db, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(ia.httpx, "post", _resp_ok("Parágrafo de venda incrível."))
    out = ia.gerar_descricao(
        "iPhone 16 Pro Max",
        marca="Apple",
        specs="- Marca: Apple\n- Memória interna: 512 GB",
    )
    # Parágrafos vêm do modelo; seção de specs é montada no código (dados reais).
    assert "Parágrafo de venda incrível." in out
    assert "Especificações técnicas:" in out
    assert "- Memória interna: 512 GB" in out
    assert "#" in out  # hashtags montadas no código


def test_sugerir_reclamacao_sucesso(temp_db, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(ia.httpx, "post", _resp_ok("Lamento o ocorrido."))
    assert ia.sugerir_reclamacao("produto veio quebrado") == "Lamento o ocorrido."


def test_resumo_do_dia_sucesso(temp_db, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(ia.httpx, "post", _resp_ok("Dia tranquilo."))
    assert ia.resumo_do_dia({"vendas_30d": 3}) == "Dia tranquilo."


def test_funcoes_ia_vazias_sem_entrada_ou_desligadas(temp_db):
    database.set_config("ia_habilitada", "1")
    assert ia.gerar_descricao("") == ""
    assert ia.sugerir_reclamacao("") == ""
    assert ia.resumo_do_dia({}) == ""
    database.set_config("ia_habilitada", "0")
    assert ia.gerar_descricao("Camiseta") == ""
    assert ia.sugerir_reclamacao("quebrou") == ""
    assert ia.resumo_do_dia({"vendas_30d": 3}) == ""


# --- Endpoints /ia/descricao, /ia/reclamacao, /ia/resumo -----------------------


def test_descricao_401_sem_login(client):
    r = client.post("/ia/descricao", data={"titulo": "x"}, follow_redirects=False)
    assert r.status_code == 401


def test_descricao_400_ia_desligada(auth_client):
    r = auth_client.post("/ia/descricao", data={"titulo": "x"})
    assert r.status_code == 400


def test_descricao_sucesso(auth_client, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(ia, "gerar_descricao", lambda *a, **k: "Uma descrição")
    r = auth_client.post("/ia/descricao", data={"titulo": "Camiseta", "marca": "Nike"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "texto": "Uma descrição"}


def test_descricao_sem_resultado(auth_client, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(ia, "gerar_descricao", lambda *a, **k: "")
    r = auth_client.post("/ia/descricao", data={"titulo": "x"})
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_reclamacao_sucesso(auth_client, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(ia, "sugerir_reclamacao", lambda *a, **k: "Resposta cordial")
    r = auth_client.post("/ia/reclamacao", data={"texto": "veio quebrado"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "sugestao": "Resposta cordial"}


def test_reclamacao_400_ia_desligada(auth_client):
    r = auth_client.post("/ia/reclamacao", data={"texto": "x"})
    assert r.status_code == 400


def test_resumo_401_sem_login(client):
    r = client.post("/ia/resumo", follow_redirects=False)
    assert r.status_code == 401


def test_resumo_sem_cache_do_painel(auth_client, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(ia, "resumo_do_dia", lambda *a, **k: "Resumo!")
    r = auth_client.post("/ia/resumo")
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_resumo_com_cache_do_painel(auth_client, monkeypatch):
    database.set_config("ia_habilitada", "1")
    database.cache_set("dashboard:13177531", '{"kpis": {"vendas_30d": 3}}')
    monkeypatch.setattr(ia, "resumo_do_dia", lambda *a, **k: "Tudo certo hoje.")
    r = auth_client.post("/ia/resumo")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["resumo"] == "Tudo certo hoje."


# --- melhorar_titulo / variar_resposta / assistente ----------------------------


def test_melhorar_titulo_trunca_60(temp_db, monkeypatch):
    database.set_config("ia_habilitada", "1")
    longo = "T" * 90
    monkeypatch.setattr(ia.httpx, "post", _resp_ok(longo))
    novo = ia.melhorar_titulo("Camiseta")
    assert len(novo) == 60


def test_melhorar_titulo_nao_corta_no_meio_da_palavra(temp_db, monkeypatch):
    database.set_config("ia_habilitada", "1")
    longo = "iPhone 16 Pro Smartphone de Alta Definicao com Camera Excelente Demais"
    monkeypatch.setattr(ia.httpx, "post", _resp_ok(longo))
    novo = ia.melhorar_titulo("iPhone")
    assert len(novo) <= 60
    assert not novo.endswith(" ")
    assert longo.startswith(novo)  # é um prefixo cortado num espaço


def test_melhorar_titulo_remove_conector_solto_no_fim(temp_db, monkeypatch):
    database.set_config("ia_habilitada", "1")
    longo = "iPhone 16 Pro Disponivel em estoque com 512GB de armazenamento interno"
    monkeypatch.setattr(ia.httpx, "post", _resp_ok(longo))
    novo = ia.melhorar_titulo("iPhone")
    assert len(novo) <= 60
    assert not novo.lower().endswith(" de")
    assert not novo.lower().endswith(" com")
    assert not novo.endswith((" ", ",", "-"))


def test_variar_resposta_sucesso(temp_db, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(ia.httpx, "post", _resp_ok("Outra forma de dizer."))
    assert ia.variar_resposta("O envio é rápido.") == "Outra forma de dizer."


def test_assistente_sucesso(temp_db, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(ia.httpx, "post", _resp_ok("Use palavras-chave no título."))
    assert ia.assistente("como melhorar o título?") == "Use palavras-chave no título."


def test_novas_funcoes_vazias_sem_entrada_ou_desligadas(temp_db):
    database.set_config("ia_habilitada", "1")
    assert ia.melhorar_titulo("") == ""
    assert ia.variar_resposta("") == ""
    assert ia.assistente("") == ""
    database.set_config("ia_habilitada", "0")
    assert ia.melhorar_titulo("Camiseta") == ""
    assert ia.variar_resposta("texto") == ""
    assert ia.assistente("duvida") == ""


# --- Endpoints /ia/titulo, /ia/variar, /ia/assistente --------------------------


def test_titulo_sucesso(auth_client, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(ia, "melhorar_titulo", lambda *a, **k: "Título melhor")
    r = auth_client.post("/ia/titulo", data={"titulo": "Camiseta", "marca": "Nike"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "texto": "Título melhor"}


def test_titulo_401_sem_login(client):
    r = client.post("/ia/titulo", data={"titulo": "x"}, follow_redirects=False)
    assert r.status_code == 401


def test_titulo_400_ia_desligada(auth_client):
    r = auth_client.post("/ia/titulo", data={"titulo": "x"})
    assert r.status_code == 400


def test_variar_sucesso(auth_client, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(ia, "variar_resposta", lambda *a, **k: "Nova versão")
    r = auth_client.post("/ia/variar", data={"texto": "Olá!"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "texto": "Nova versão"}


def test_variar_400_ia_desligada(auth_client):
    r = auth_client.post("/ia/variar", data={"texto": "x"})
    assert r.status_code == 400


def test_assistente_endpoint_sucesso(auth_client, monkeypatch):
    database.set_config("ia_habilitada", "1")
    monkeypatch.setattr(ia, "assistente", lambda *a, **k: "Dica prática")
    r = auth_client.post("/ia/assistente", data={"pergunta": "como vender mais?"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "resposta": "Dica prática"}


def test_assistente_endpoint_401_sem_login(client):
    r = client.post("/ia/assistente", data={"pergunta": "x"}, follow_redirects=False)
    assert r.status_code == 401


# --- Página /assistente --------------------------------------------------------


def test_assistente_page_redireciona_sem_login(client):
    r = client.get("/assistente", follow_redirects=False)
    assert r.status_code in (302, 303, 307)
    assert r.headers["location"] == "/entrar"


def test_assistente_page_ia_desligada(auth_client):
    r = auth_client.get("/assistente")
    assert r.status_code == 200
    assert "desligada" in r.text


def test_assistente_page_ia_ligada(auth_client):
    database.set_config("ia_habilitada", "1")
    r = auth_client.get("/assistente")
    assert r.status_code == 200
    assert 'id="ia-pergunta"' in r.text
