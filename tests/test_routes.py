"""Testes das rotas HTTP (fluxos de autenticação, telas e ações)."""

import pytest

from app import database


# --- Fluxo de conta / autenticação --------------------------------------------

def test_home_sem_usuario_redireciona_criar_conta(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/criar-conta"


def test_criar_conta_get(client):
    assert client.get("/criar-conta").status_code == 200


def test_criar_conta_valida_e_cria(client):
    r = client.post(
        "/criar-conta",
        data={"username": "novo", "password": "senha123", "confirm": "senha123"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/configuracao"
    assert database.has_user() is True


@pytest.mark.parametrize(
    "data",
    [
        {"username": "ab", "password": "senha123", "confirm": "senha123"},
        {"username": "valido", "password": "123", "confirm": "123"},
        {"username": "valido", "password": "senha123", "confirm": "outra"},
    ],
)
def test_criar_conta_invalida(client, data):
    r = client.post("/criar-conta", data=data, follow_redirects=False)
    assert r.status_code == 200  # renderiza com erro
    assert database.has_user() is False


def test_entrar_invalido(client):
    database.create_user("joao", *reversed(_hash("senha123")))
    r = client.post(
        "/entrar",
        data={"username": "joao", "password": "errada"},
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert "inválidos" in r.text


def test_entrar_valido_e_sair(client):
    salt, ph = _hash("senha123")
    database.create_user("joao", ph, salt)
    r = client.post(
        "/entrar",
        data={"username": "joao", "password": "senha123"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    r2 = client.get("/sair", follow_redirects=False)
    assert r2.status_code == 303
    assert r2.headers["location"] == "/entrar"


def _hash(pw):
    from app import auth
    return auth.hash_password(pw)


# --- Telas autenticadas (smoke) -----------------------------------------------

GET_ROUTES = [
    "/",
    "/configuracao",
    "/publicar",
    "/anuncios",
    "/vendas",
    "/vendas/exportar",
    "/pos-venda",
    "/estatisticas",
    "/lucratividade",
    "/lucratividade/exportar",
    "/tendencias",
    "/historico",
    "/promocoes",
    "/agendamentos",
    "/respostas",
]


@pytest.mark.parametrize("path", GET_ROUTES)
def test_get_routes_autenticado(auth_client, path):
    r = auth_client.get(path, follow_redirects=False)
    assert r.status_code == 200


GET_ITEM_ROUTES = [
    "/anuncios/MLB1/editar",
    "/anuncios/MLB1/qualidade",
    "/anuncios/MLB1/concorrencia",
    "/promocoes/MLB1",
    "/vendas/OID1/mensagens",
]


@pytest.mark.parametrize("path", GET_ITEM_ROUTES)
def test_get_item_routes(auth_client, path):
    assert auth_client.get(path, follow_redirects=False).status_code == 200


def test_rotas_exigem_login(client):
    # Sem sessão, /anuncios volta para criar-conta (não há usuário ainda).
    r = client.get("/anuncios", follow_redirects=False)
    assert r.status_code == 303


# --- Ações (POST) --------------------------------------------------------------

def test_configuracao_save(auth_client):
    r = auth_client.post(
        "/configuracao",
        data={
            "client_id": "abc",
            "client_secret": "",
            "redirect_uri": "https://x/callback.html",
            "estoque_baixo": 5,
            "cache_ttl_min": 10,
        },
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert database.get_config("estoque_baixo") == "5"


def test_publicar(auth_client):
    r = auth_client.post(
        "/publicar",
        data={"title": "Meu produto novo de teste", "price": 99.9,
              "available_quantity": 3, "condition": "new",
              "listing_type_id": "gold_special", "category_id": "MLB1234"},
        follow_redirects=False,
    )
    assert r.status_code == 200


def test_anuncio_status(auth_client):
    r = auth_client.post(
        "/anuncios/MLB1/status", data={"status": "paused"}, follow_redirects=False
    )
    assert r.status_code == 303


def test_anuncio_status_invalido(auth_client):
    r = auth_client.post(
        "/anuncios/MLB1/status", data={"status": "zzz"}, follow_redirects=False
    )
    assert r.status_code == 303


def test_anuncio_duplicar(auth_client):
    r = auth_client.post("/anuncios/MLB1/duplicar", follow_redirects=False)
    assert r.status_code == 303


def test_anuncios_massa(auth_client):
    r = auth_client.post(
        "/anuncios/massa",
        data={"acao": "preco", "valor": 50, "item_ids": ["MLB1"]},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_editar_anuncio_post(auth_client):
    r = auth_client.post(
        "/anuncios/MLB1/editar",
        data={"price": 120, "available_quantity": 4,
              "title": "Titulo editado do anuncio", "description": "nova descricao"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_aplicar_preco(auth_client):
    r = auth_client.post(
        "/anuncios/MLB1/preco", data={"price": 88.5}, follow_redirects=False
    )
    assert r.status_code == 303


def test_enviar_mensagem(auth_client):
    r = auth_client.post(
        "/vendas/OID1/mensagens",
        data={"pack_id": "OID1", "buyer_id": 9, "text": "Olá"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_responder_pergunta(auth_client):
    r = auth_client.post(
        "/pos-venda/responder",
        data={"question_id": 1, "text": "Resposta"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_responder_massa(auth_client):
    r = auth_client.post(
        "/pos-venda/responder-massa",
        data={"text": "Resposta padrão", "question_ids": [1, 2]},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_responder_massa_sem_selecao(auth_client):
    r = auth_client.post(
        "/pos-venda/responder-massa",
        data={"text": "Resposta"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_promocoes_aplicar_remover(auth_client):
    r1 = auth_client.post(
        "/promocoes/MLB1/aplicar",
        data={"promotion_id": "P1", "promotion_type": "DEAL", "deal_price": 80},
        follow_redirects=False,
    )
    assert r1.status_code == 303
    r2 = auth_client.post(
        "/promocoes/MLB1/remover",
        data={"promotion_id": "P1", "promotion_type": "DEAL"},
        follow_redirects=False,
    )
    assert r2.status_code == 303


def test_agendamentos(auth_client):
    from datetime import datetime, timedelta
    futuro = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    r = auth_client.post(
        "/agendamentos",
        data={"tipo": "pausar", "item_id": "MLB1", "quando": futuro, "valor": 0},
        follow_redirects=False,
    )
    assert r.status_code == 303
    tarefas = database.list_tasks()
    assert len(tarefas) == 1
    r2 = auth_client.post(
        f"/agendamentos/{tarefas[0]['id']}/cancelar", follow_redirects=False
    )
    assert r2.status_code == 303


def test_agendamento_data_passada(auth_client):
    r = auth_client.post(
        "/agendamentos",
        data={"tipo": "pausar", "item_id": "MLB1", "quando": "2000-01-01T00:00",
              "valor": 0},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert database.list_tasks() == []


def test_respostas_crud(auth_client):
    r = auth_client.post(
        "/respostas",
        data={"titulo": "Saudação", "texto": "Olá, tudo bem?"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    rid = database.list_quick_replies()[0]["id"]
    r2 = auth_client.post(f"/respostas/{rid}/excluir", follow_redirects=False)
    assert r2.status_code == 303
    assert database.list_quick_replies() == []


# --- OAuth ---------------------------------------------------------------------

def test_conectar_redireciona(auth_client):
    r = auth_client.get("/mercadolivre/conectar", follow_redirects=False)
    assert r.status_code in (302, 303, 307)


def test_desconectar(auth_client):
    r = auth_client.get("/mercadolivre/desconectar", follow_redirects=False)
    assert r.status_code == 303
    assert database.get_token() is None
