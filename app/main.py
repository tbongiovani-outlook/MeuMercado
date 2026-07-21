"""Aplicação FastAPI — Meu Mercado.

Fluxo de uso (fácil para o usuário final, roda em Windows e macOS):
  1. Primeiro acesso  -> cria a conta local (usuário + senha com hash de mão única)
  2. Login local      -> entra com usuário e senha
  3. Configuração     -> informa o Client ID / Secret do Mercado Livre
  4. Conectar         -> autoriza no Mercado Livre (OAuth) e vê os dados
"""

import secrets
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import asyncio
import csv
import io
import json
import re
import time

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from urllib.parse import urlsplit

from . import auth, database, meli, quality, telemetry
from .config import settings

# Configura logging em arquivo assim que o módulo é importado.
logger = telemetry.setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    logger.info("Aplicação iniciada. Banco pronto em %s", settings.database_path)
    tarefa = asyncio.create_task(_scheduler_loop())
    yield
    tarefa.cancel()
    logger.info("Aplicação finalizada.")


async def _scheduler_loop():
    """Verifica periodicamente as ações agendadas e executa as vencidas."""
    while True:
        try:
            await asyncio.sleep(60)
            await asyncio.to_thread(_run_due_tasks)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Falha no laço do agendador")


def _run_due_tasks() -> None:
    """Executa as ações agendadas cujo horário já chegou (best-effort)."""
    for tarefa in database.due_tasks(int(time.time())):
        try:
            _executar_tarefa(tarefa)
            database.finish_task(tarefa["id"], "concluida", "ok")
            logger.info("Ação agendada %s executada (%s em %s)",
                        tarefa["id"], tarefa["tipo"], tarefa["item_id"])
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha ao executar ação agendada %s", tarefa["id"])
            database.finish_task(tarefa["id"], "erro", str(exc)[:200])


def _executar_tarefa(tarefa: dict) -> None:
    tipo = tarefa["tipo"]
    item_id = tarefa["item_id"]
    if tipo in {"pausar", "reativar", "encerrar"}:
        status = {"pausar": "paused", "reativar": "active", "encerrar": "closed"}[tipo]
        meli.update_item_status(item_id, status)
    elif tipo == "preco":
        meli.update_item(item_id, {"price": round(tarefa["valor"] or 0, 2)})
    else:
        raise ValueError(f"Tipo de ação desconhecido: {tipo}")



app = FastAPI(title="Meu Mercado", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.app_secret_key,
    same_site="lax",
    https_only=False,
)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

_METODOS_INSEGUROS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def _csrf_protecao(request: Request, call_next):
    """Defesa CSRF: em requisições que alteram estado, exige Origin/Referer do próprio site."""
    if request.method in _METODOS_INSEGUROS:
        host = request.headers.get("host", "")
        origem = request.headers.get("origin") or request.headers.get("referer") or ""
        if origem:
            host_origem = urlsplit(origem).netloc
            if host_origem and host_origem != host:
                logger.warning("CSRF bloqueado: origem=%s host=%s", origem, host)
                return PlainTextResponse(
                    "Requisição bloqueada por segurança (CSRF).", status_code=403
                )
    return await call_next(request)


def _pagina_erro(request, *, codigo, titulo, mensagem, detalhe, icone, status):
    """Renderiza a página de erro com a identidade do app; degrada para texto puro."""
    try:
        ctx = _base_context(request)
    except Exception:  # noqa: BLE001 — em erro grave o contexto pode falhar
        ctx = {"username": "", "error": None, "flash": None, "badges": {}}
    ctx.update(
        {
            "codigo": codigo,
            "titulo": titulo,
            "mensagem": mensagem,
            "detalhe": detalhe,
            "icone": icone,
        }
    )
    try:
        return templates.TemplateResponse(request, "erro.html", ctx, status_code=status)
    except Exception:  # noqa: BLE001
        return PlainTextResponse(f"{codigo} — {titulo}", status_code=status)


@app.exception_handler(StarletteHTTPException)
async def _erro_http(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return _pagina_erro(
            request,
            codigo=404,
            titulo="Página não encontrada",
            mensagem="O endereço que você tentou abrir não existe por aqui.",
            detalhe="Verifique o link ou volte para o painel principal.",
            icone="🧭",
            status=404,
        )
    if exc.status_code >= 500:
        return _pagina_erro(
            request,
            codigo=exc.status_code,
            titulo="Algo deu errado",
            mensagem="Tivemos um problema ao processar sua solicitação.",
            detalhe="Tente novamente em instantes. Se persistir, reinicie o app.",
            icone="🛠️",
            status=exc.status_code,
        )
    # Demais erros HTTP (401/403/405…): resposta simples, sem página completa.
    return PlainTextResponse(str(exc.detail), status_code=exc.status_code)


@app.exception_handler(Exception)
async def _erro_interno(request: Request, exc: Exception):
    logger.exception("Erro interno não tratado: %s", exc)
    return _pagina_erro(
        request,
        codigo=500,
        titulo="Algo deu errado",
        mensagem="Tivemos um problema ao processar sua solicitação.",
        detalhe="Tente novamente em instantes. Se persistir, reinicie o app.",
        icone="🛠️",
        status=500,
    )


def _datetimebr(epoch: int | None) -> str:
    """Formata um timestamp epoch como data/hora local (dd/mm/aaaa HH:MM)."""
    if not epoch:
        return "—"
    return datetime.fromtimestamp(int(epoch)).strftime("%d/%m/%Y %H:%M")


templates.env.filters["datetimebr"] = _datetimebr


def _cache_ttl_segundos() -> int:
    """Validade do cache (em segundos), configurável em /configuracao."""
    try:
        return max(0, int(database.get_config("cache_ttl_min") or 15)) * 60
    except (TypeError, ValueError):
        return 15 * 60


def _cache_ler(chave: str, force: bool = False):
    """Retorna (dados, atualizado_em) se houver cache válido; senão None."""
    if force:
        return None
    row = database.cache_get(chave)
    if not row:
        return None
    if time.time() - row["atualizado_em"] > _cache_ttl_segundos():
        return None
    try:
        return json.loads(row["valor"]), row["atualizado_em"]
    except (ValueError, TypeError):
        return None


def _cache_gravar(chave: str, dados) -> int:
    """Grava os dados no cache e retorna o timestamp."""
    return database.cache_set(chave, json.dumps(dados, default=str))


def _invalidar_cache_itens() -> None:
    """Descarta o cache de anúncios/promoções após uma alteração de itens."""
    try:
        me, _ = _me_cached()
        uid = me["id"]
        database.cache_delete(f"anuncios:{uid}")
        database.cache_delete(f"promocoes:{uid}")
    except Exception:  # noqa: BLE001 — invalidação nunca deve quebrar a ação
        logger.debug("Não foi possível invalidar o cache de itens.", exc_info=True)


def _me_cached(force: bool = False):
    """Dados da conta (/users/me) com cache — evita 1 chamada por página."""
    cached = _cache_ler("me", force=force)
    if cached:
        return cached[0], cached[1]
    me = meli.api_get("/users/me")
    return me, _cache_gravar("me", me)


def _nav_badges() -> dict:
    """Contadores do menu (perguntas pendentes e vendas novas), lidos do cache."""
    row = database.cache_get("nav_badges")
    if not row:
        return {"perguntas": 0, "vendas": 0}
    try:
        dados = json.loads(row["valor"])
        return {"perguntas": int(dados.get("perguntas", 0)), "vendas": int(dados.get("vendas", 0))}
    except (ValueError, TypeError):
        return {"perguntas": 0, "vendas": 0}

# Instrumenta a aplicação com OpenTelemetry.
telemetry.setup_telemetry(app)


def _current_user_id(request: Request):
    return request.session.get("user_id")


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def _order_dt(order: dict) -> datetime | None:
    ds = order.get("date_created")
    if not ds:
        return None
    try:
        return datetime.fromisoformat(ds)
    except ValueError:
        return None


def _limite_estoque_baixo() -> int:
    valor = database.get_config("estoque_baixo")
    try:
        return int(valor) if valor is not None else 3
    except (TypeError, ValueError):
        return 3


def _trend(atual: float, anterior: float) -> dict:
    """Compara o valor atual com o do período anterior."""
    if anterior <= 0:
        return {"dir": "up" if atual > 0 else "flat", "pct": None}
    pct = round((atual - anterior) / anterior * 100)
    return {"dir": "up" if pct > 0 else "down" if pct < 0 else "flat", "pct": pct}


def _destaques_ativos(detalhes: list[dict]) -> tuple[dict | None, dict | None]:
    """Retorna (mais vendido, menos vendido) entre os anúncios ativos."""
    ativos = [d for d in detalhes if d.get("status") == "active"]
    if not ativos:
        return None, None
    mais = max(ativos, key=lambda d: d.get("sold_quantity") or 0)
    menos = min(ativos, key=lambda d: d.get("sold_quantity") or 0)
    return mais, menos


def _count_acima_concorrencia(detalhes: list[dict], limite: int = 12) -> int:
    """Conta anúncios ativos de catálogo com preço acima do menor concorrente."""
    candidatos = [
        d for d in detalhes
        if d.get("status") == "active"
        and d.get("catalog_product_id")
        and d.get("price") is not None
    ][:limite]
    if not candidatos:
        return 0

    def _esta_acima(d: dict) -> bool:
        try:
            comps = meli.get_catalog_competitors(d["catalog_product_id"])
        except Exception:  # noqa: BLE001
            return False
        precos = [
            float(c["price"]) for c in comps
            if c.get("price") and c.get("id") != d.get("id")
        ]
        return bool(precos and float(d["price"]) > min(precos))

    with ThreadPoolExecutor(max_workers=6) as executor:
        return sum(1 for acima in executor.map(_esta_acima, candidatos) if acima)


def _orders_metrics(orders: list[dict], agora: datetime) -> dict:
    """Métricas de vendas dos últimos 30 dias + tendência e série diária."""
    ini_atual = agora - timedelta(days=30)
    ini_anterior = agora - timedelta(days=60)
    atuais: list[dict] = []
    anteriores: list[dict] = []
    por_dia = [0] * 30
    for o in orders:
        dt = _order_dt(o)
        if not dt:
            continue
        if dt >= ini_atual:
            atuais.append(o)
            idx = (agora - dt).days
            if 0 <= idx < 30:
                por_dia[29 - idx] += 1
        elif dt >= ini_anterior:
            anteriores.append(o)

    fat = sum(float(o.get("total_amount") or 0) for o in atuais)
    com = sum(
        float(i.get("sale_fee") or 0)
        for o in atuais for i in o.get("order_items", [])
    )
    fat_ant = sum(float(o.get("total_amount") or 0) for o in anteriores)
    return {
        "vendas_30d": len(atuais),
        "vendas_7d": sum(por_dia[-7:]),
        "faturamento_30d": round(fat, 2),
        "comissoes_30d": round(com, 2),
        "liquido_30d": round(fat - com, 2),
        "ticket_medio": round(fat / len(atuais), 2) if atuais else 0.0,
        "trend_vendas": _trend(len(atuais), len(anteriores)),
        "trend_faturamento": _trend(fat, fat_ant),
        "vendas_por_dia": por_dia,
    }


def _dashboard_metrics(ml_user: dict) -> dict:
    """Calcula os KPIs do painel principal a partir da API do Mercado Livre."""
    kpis = {
        "anuncios_ativos": 0, "anuncios_total": 0, "sem_estoque": 0,
        "vendas_30d": 0, "vendas_7d": 0, "faturamento_30d": 0.0, "comissoes_30d": 0.0,
        "liquido_30d": 0.0, "ticket_medio": 0.0, "acima_concorrencia": 0,
        "perguntas_pendentes": 0, "reclamacoes_abertas": 0,
        "estoque_baixo": 0, "limite_estoque": 3,
        "trend_vendas": None, "trend_faturamento": None, "vendas_por_dia": [],
        "mais_vendido": None, "menos_vendido": None,
        "reputacao": (ml_user.get("seller_reputation") or {}).get("level_id"),
    }
    acoes: list[dict] = []
    avisos: list[str] = []
    orders: list[dict] = []
    uid = ml_user["id"]
    agora = datetime.now(timezone.utc)
    date_from = (agora - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S.000-00:00")

    # Busca as 4 fontes em paralelo (a API do ML responde ~1s por chamada).
    with ThreadPoolExecutor(max_workers=4) as executor:
        f_itens = executor.submit(
            lambda: meli.get_items_details(meli.list_item_ids(uid, limit=50))
        )
        f_pedidos = executor.submit(meli.search_orders, uid, 50, date_from)
        f_perguntas = executor.submit(meli.search_questions, uid)
        f_reclamacoes = executor.submit(meli.search_claims)

    try:
        detalhes = f_itens.result()
        kpis["anuncios_total"] = len(detalhes)
        kpis["anuncios_ativos"] = sum(1 for d in detalhes if d.get("status") == "active")
        kpis["sem_estoque"] = sum(
            1 for d in detalhes
            if d.get("status") == "active" and (d.get("available_quantity") or 0) == 0
        )
        limite = _limite_estoque_baixo()
        kpis["limite_estoque"] = limite
        kpis["estoque_baixo"] = sum(
            1 for d in detalhes
            if d.get("status") == "active"
            and 0 < (d.get("available_quantity") or 0) <= limite
        )
        kpis["acima_concorrencia"] = _count_acima_concorrencia(detalhes)
        kpis["mais_vendido"], kpis["menos_vendido"] = _destaques_ativos(detalhes)
    except Exception as exc:  # noqa: BLE001
        avisos.append(
            "Não foi possível ler os anúncios — habilite a permissão "
            "\"Publicação e sincronização\" e reconecte. "
            f"(detalhe: {exc})"
        )

    try:
        orders = f_pedidos.result()
        kpis.update(_orders_metrics(orders, agora))
    except Exception as exc:  # noqa: BLE001
        avisos.append(
            "Não foi possível ler as vendas — verifique a permissão de "
            f"pedidos e reconecte. (detalhe: {exc})"
        )

    try:
        q = f_perguntas.result()
        kpis["perguntas_pendentes"] = q.get("total") or len(q.get("questions", []))
    except Exception:  # noqa: BLE001
        pass

    try:
        c = f_reclamacoes.result()
        kpis["reclamacoes_abertas"] = (c.get("paging") or {}).get("total") or len(
            c.get("data", c.get("results", []))
        )
    except Exception:  # noqa: BLE001
        pass

    if kpis["perguntas_pendentes"]:
        acoes.append({"tipo": "warn", "link": "/pos-venda",
                      "texto": f"{kpis['perguntas_pendentes']} pergunta(s) sem resposta"})
    if kpis["reclamacoes_abertas"]:
        acoes.append({"tipo": "error", "link": "/pos-venda",
                      "texto": f"{kpis['reclamacoes_abertas']} reclamação(ões) aberta(s)"})
    if kpis["sem_estoque"]:
        acoes.append({"tipo": "warn", "link": "/anuncios",
                      "texto": f"{kpis['sem_estoque']} anúncio(s) ativo(s) sem estoque"})
    if kpis["estoque_baixo"]:
        acoes.append({"tipo": "warn", "link": "/anuncios",
                      "texto": f"{kpis['estoque_baixo']} anúncio(s) com estoque baixo "
                               f"(≤ {kpis['limite_estoque']})"})
    if kpis["acima_concorrencia"]:
        acoes.append({"tipo": "warn", "link": "/anuncios",
                      "texto": f"{kpis['acima_concorrencia']} anúncio(s) com preço acima da concorrência"})

    return {"kpis": kpis, "acoes": acoes, "avisos": avisos, "orders": orders[:10]}


# ---------------------------------------------------------------------------
# Painel principal
# ---------------------------------------------------------------------------
@app.get("/")
def home(request: Request, atualizar: int = 0):
    if not database.has_user():
        return _redirect("/criar-conta")
    if not _current_user_id(request):
        return _redirect("/entrar")

    user = database.get_user()
    context = {
        "username": user["username"],
        "configured": meli.is_configured(),
        "connected": bool(database.get_token()),
        "ml_user": None,
        "orders": [],
        "kpis": None,
        "acoes": [],
        "cache_em": None,
        "error": request.session.pop("flash", None),
    }

    if context["configured"] and context["connected"]:
        try:
            context["ml_user"], _ = _me_cached(force=bool(atualizar))
        except Exception as exc:  # noqa: BLE001
            context["error"] = f"Não foi possível ler os dados da conta: {exc}"

        if context["ml_user"]:
            chave = f"dashboard:{context['ml_user']['id']}"
            cached = _cache_ler(chave, force=bool(atualizar))
            if cached:
                dados, quando = cached
                context["cache_em"] = quando
            else:
                dados = _dashboard_metrics(context["ml_user"])
                context["cache_em"] = _cache_gravar(chave, dados)
                _registrar_snapshot(dados["kpis"])
            context["kpis"] = dados["kpis"]
            context["acoes"] = dados["acoes"]
            context["orders"] = dados["orders"]
            if dados["avisos"] and not context["error"]:
                context["error"] = " · ".join(dados["avisos"])
            _cache_gravar("nav_badges", {
                "perguntas": (dados["kpis"].get("perguntas_pendentes", 0)
                              + dados["kpis"].get("reclamacoes_abertas", 0)),
                "vendas": dados["kpis"].get("vendas_7d", 0),
            })

    context["badges"] = _nav_badges()
    return templates.TemplateResponse(request, "dashboard.html", context)


def _registrar_snapshot(kpis: dict) -> None:
    """Grava o resumo do dia para montar o histórico (best-effort)."""
    try:
        hoje = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        database.save_snapshot(hoje, {
            "vendas": kpis.get("vendas_30d", 0),
            "faturamento": kpis.get("faturamento_30d", 0.0),
            "liquido": kpis.get("liquido_30d", 0.0),
            "ativos": kpis.get("anuncios_ativos", 0),
            "sem_estoque": kpis.get("sem_estoque", 0),
            "perguntas": kpis.get("perguntas_pendentes", 0),
            "reclamacoes": kpis.get("reclamacoes_abertas", 0),
        })
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao gravar snapshot diário")


# ---------------------------------------------------------------------------
# Conta local: criar (primeiro acesso), entrar e sair
# ---------------------------------------------------------------------------
@app.get("/criar-conta")
def criar_conta_form(request: Request):
    if database.has_user():
        return _redirect("/entrar")
    return templates.TemplateResponse(request, "criar_conta.html", {"error": None})


@app.post("/criar-conta")
def criar_conta(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    confirm: str = Form(...),
):
    if database.has_user():
        return _redirect("/entrar")

    username = username.strip()
    error = None
    if len(username) < 3:
        error = "O usuário deve ter ao menos 3 caracteres."
    elif len(password) < 6:
        error = "A senha deve ter ao menos 6 caracteres."
    elif password != confirm:
        error = "As senhas não conferem."

    if error:
        return templates.TemplateResponse(
            request, "criar_conta.html", {"error": error}
        )

    salt, password_hash = auth.hash_password(password)
    user_id = database.create_user(username, password_hash, salt)
    request.session["user_id"] = user_id
    logger.info("Conta local criada: %s (id=%s)", username, user_id)
    return _redirect("/configuracao")


@app.get("/entrar")
def entrar_form(request: Request):
    if not database.has_user():
        return _redirect("/criar-conta")
    return templates.TemplateResponse(request, "entrar.html", {"error": None})


@app.post("/entrar")
def entrar(request: Request, username: str = Form(...), password: str = Form(...)):
    user = database.get_user_by_username(username.strip())
    if not user or not auth.verify_password(
        password, user["salt"], user["password_hash"]
    ):
        return templates.TemplateResponse(
            request, "entrar.html", {"error": "Usuário ou senha inválidos."}
        )
    request.session["user_id"] = user["id"]
    return _redirect("/")


@app.get("/sair")
def sair(request: Request):
    request.session.clear()
    return _redirect("/entrar")


# ---------------------------------------------------------------------------
# Configuração das credenciais do Mercado Livre
# ---------------------------------------------------------------------------
@app.get("/configuracao")
def configuracao_form(request: Request):
    if not _current_user_id(request):
        return _redirect("/entrar")
    conectado, conta = _conta_conectada()
    context = {
        "error": None,
        "saved": False,
        "client_id": meli.get_client_id(),
        "has_secret": bool(meli.get_client_secret()),
        "redirect_uri": meli.get_redirect_uri(),
        "estoque_baixo": _limite_estoque_baixo(),
        "cache_ttl_min": int(database.get_config("cache_ttl_min") or 15),
        "connected": conectado,
        "ml_user": conta,
        "badges": _nav_badges(),
    }
    return templates.TemplateResponse(request, "configuracao.html", context)


def _conta_conectada():
    """Retorna (conectado, dados_da_conta) usando o cache, sem travar a tela."""
    if not database.get_token():
        return False, None
    try:
        conta, _ = _me_cached()
        return True, conta
    except Exception:  # noqa: BLE001
        return True, None


@app.post("/configuracao")
def configuracao_save(
    request: Request,
    client_id: str = Form(""),
    client_secret: str = Form(""),
    redirect_uri: str = Form(""),
    estoque_baixo: int = Form(3),
    cache_ttl_min: int = Form(15),
):
    if not _current_user_id(request):
        return _redirect("/entrar")

    database.set_config("meli_client_id", client_id.strip())
    database.set_config("meli_redirect_uri", redirect_uri.strip())
    database.set_config("estoque_baixo", str(max(0, estoque_baixo)))
    database.set_config("cache_ttl_min", str(max(0, cache_ttl_min)))
    # Só sobrescreve o secret se o usuário digitou um novo (mantém o atual se vazio).
    if client_secret.strip():
        database.set_config("meli_client_secret", client_secret.strip())

    context = {
        "error": None,
        "saved": True,
        "client_id": meli.get_client_id(),
        "has_secret": bool(meli.get_client_secret()),
        "redirect_uri": meli.get_redirect_uri(),
        "estoque_baixo": _limite_estoque_baixo(),
        "cache_ttl_min": int(database.get_config("cache_ttl_min") or 15),
        "connected": _conta_conectada()[0],
        "ml_user": _conta_conectada()[1],
        "badges": _nav_badges(),
    }
    return templates.TemplateResponse(request, "configuracao.html", context)


# ---------------------------------------------------------------------------
# Conexão OAuth com o Mercado Livre
# ---------------------------------------------------------------------------
@app.get("/mercadolivre/conectar")
def ml_conectar(request: Request):
    if not _current_user_id(request):
        return _redirect("/entrar")
    if not meli.is_configured():
        return _redirect("/configuracao")
    state = secrets.token_urlsafe(24)
    verifier, challenge = meli.generate_pkce_pair()
    request.session["oauth_state"] = state
    request.session["pkce_verifier"] = verifier
    return RedirectResponse(meli.build_authorization_url(state, challenge))


@app.get("/callback")
def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if not _current_user_id(request):
        return _redirect("/entrar")

    if error:
        request.session["flash"] = f"Autorização negada: {error}"
        return _redirect("/")

    expected = request.session.get("oauth_state")
    if not state or state != expected:
        request.session["flash"] = "Parâmetro 'state' inválido (possível CSRF)."
        return _redirect("/")

    if not code:
        return _redirect("/")

    verifier = request.session.get("pkce_verifier")
    if not verifier:
        request.session["flash"] = "Sessão de autorização expirada. Tente conectar novamente."
        return _redirect("/")

    try:
        meli.exchange_code(code, verifier)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao trocar code por token")
        request.session["flash"] = f"Falha ao conectar ao Mercado Livre: {exc}"
        return _redirect("/")

    request.session.pop("oauth_state", None)
    request.session.pop("pkce_verifier", None)
    logger.info("Conta do Mercado Livre conectada com sucesso.")
    return _redirect("/")


@app.get("/mercadolivre/desconectar")
def ml_desconectar(request: Request):
    if not _current_user_id(request):
        return _redirect("/entrar")
    database.clear_tokens()
    request.session["flash"] = "Conta do Mercado Livre desconectada."
    return _redirect("/")


# ---------------------------------------------------------------------------
# Helpers das páginas autenticadas
# ---------------------------------------------------------------------------
def _require_ready(request: Request):
    """Retorna (erro_redirect, ml_user) — redireciona se faltar login/conexão."""
    if not database.has_user():
        return _redirect("/criar-conta"), None
    if not _current_user_id(request):
        return _redirect("/entrar"), None
    if not meli.is_configured() or not database.get_token():
        return _redirect("/"), None
    return None, database.get_user()


def _base_context(request: Request) -> dict:
    user = database.get_user()
    return {
        "username": user["username"] if user else "",
        "error": None,
        "flash": request.session.pop("flash", None),
        "badges": _nav_badges(),
    }


# ---------------------------------------------------------------------------
# Publicar anúncio
# ---------------------------------------------------------------------------
@app.get("/publicar")
def publicar_form(request: Request):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    ctx = _base_context(request)
    ctx.update({"resultado": None, "form": {}})
    return templates.TemplateResponse(request, "publicar.html", ctx)


@app.post("/publicar")
def publicar(
    request: Request,
    title: str = Form(...),
    price: float = Form(...),
    available_quantity: int = Form(1),
    condition: str = Form("new"),
    listing_type_id: str = Form("free"),
    image_url: str = Form(""),
    marca: str = Form(""),
    gtin: str = Form(""),
    category_id: str = Form(""),
    image_file: UploadFile | None = File(None),
):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect

    ctx = _base_context(request)
    form = {
        "title": title,
        "price": price,
        "available_quantity": available_quantity,
        "condition": condition,
        "listing_type_id": listing_type_id,
        "image_url": image_url,
        "marca": marca,
        "gtin": gtin,
        "category_id": category_id,
    }
    resultado = {"ok": False, "item": None, "erro": None, "category_id": category_id,
                 "catalog_product": None}

    try:
        if not category_id:
            pred = meli.predict_category(title)
            category_id = pred.get("category_id", "")
            resultado["category_id"] = category_id
        if not category_id:
            raise RuntimeError("Não foi possível prever a categoria para este título.")

        pictures = None
        if image_file is not None and image_file.filename:
            picture_id = meli.upload_picture(
                image_file.file.read(),
                image_file.filename,
                image_file.content_type or "image/jpeg",
            )
            if picture_id:
                pictures = [{"id": picture_id}]
        elif image_url.strip():
            pictures = [{"source": image_url.strip()}]

        res = meli.publish(
            title=title,
            category_id=category_id,
            price=price,
            available_quantity=available_quantity,
            condition=condition,
            listing_type_id=listing_type_id,
            brand=marca,
            gtin=gtin,
            pictures=pictures,
        )
        resultado["ok"] = True
        resultado["item"] = res["item"]
        resultado["catalog_product"] = res["catalog_product"]
        _invalidar_cache_itens()
        logger.info(
            "Anúncio publicado: %s (%s)",
            res["item"].get("id"),
            res["item"].get("title"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao publicar anúncio")
        resultado["erro"] = str(exc)

    ctx.update({"resultado": resultado, "form": form})
    return templates.TemplateResponse(request, "publicar.html", ctx)


# ---------------------------------------------------------------------------
# Anúncios (histórico)
# ---------------------------------------------------------------------------
@app.get("/anuncios")
def anuncios(
    request: Request,
    q: str = "",
    status: str = "",
    pagina: int = 1,
    atualizar: int = 0,
):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    ctx = _base_context(request)
    items = []
    cache_em = None
    force = bool(atualizar)
    try:
        me, _ = _me_cached(force=force)
        chave = f"anuncios:{me['id']}"
        cached = _cache_ler(chave, force=force)
        if cached:
            items, cache_em = cached
        else:
            ids = meli.list_all_item_ids(me["id"])
            items = meli.get_items_details(ids)
            cache_em = _cache_gravar(chave, items)
    except Exception as exc:  # noqa: BLE001
        ctx["error"] = f"Não foi possível carregar os anúncios: {exc}"

    termo = q.strip().lower()
    if termo:
        items = [it for it in items if termo in (it.get("title") or "").lower()]
    if status:
        items = [it for it in items if it.get("status") == status]

    por_pagina = 20
    total = len(items)
    total_paginas = max(1, (total + por_pagina - 1) // por_pagina)
    pagina = max(1, min(pagina, total_paginas))
    inicio = (pagina - 1) * por_pagina
    ctx.update({
        "items": items[inicio : inicio + por_pagina],
        "q": q,
        "status_filtro": status,
        "pagina": pagina,
        "total_paginas": total_paginas,
        "total_itens": total,
        "cache_em": cache_em,
    })
    return templates.TemplateResponse(request, "anuncios.html", ctx)


@app.post("/anuncios/{item_id}/status")
def anuncio_status(request: Request, item_id: str, status: str = Form(...)):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    if status not in {"active", "paused", "closed"}:
        request.session["flash"] = "Status inválido."
        return _redirect("/anuncios")
    try:
        meli.update_item_status(item_id, status)
        _invalidar_cache_itens()
        rotulos = {"active": "reativado", "paused": "pausado", "closed": "encerrado"}
        request.session["flash"] = f"Anúncio {item_id} {rotulos[status]}."
        logger.info("Anúncio %s alterado para %s", item_id, status)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao alterar status do anúncio")
        request.session["flash"] = f"Não foi possível alterar o anúncio: {exc}"
    return _redirect("/anuncios")


@app.post("/anuncios/{item_id}/duplicar")
def duplicar_anuncio(request: Request, item_id: str):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    try:
        novo = meli.duplicate_item(item_id)
        novo_id = novo.get("id", "?")
        _invalidar_cache_itens()
        if novo_id and novo_id != "?":
            try:
                meli.update_item_status(novo_id, "paused")
            except Exception:  # noqa: BLE001
                logger.warning("Duplicado %s criado, mas não foi possível pausar.", novo_id)
            request.session["flash"] = (
                "Cópia criada (pausada). Revise preço e estoque e ative quando quiser."
            )
            logger.info("Anúncio %s duplicado em %s", item_id, novo_id)
            return _redirect(f"/anuncios/{novo_id}/editar")
        request.session["flash"] = f"Anúncio duplicado: {novo_id}."
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao duplicar anúncio")
        request.session["flash"] = f"Não foi possível duplicar o anúncio: {exc}"
    return _redirect("/anuncios")


@app.post("/anuncios/massa")
def anuncios_massa(
    request: Request,
    acao: str = Form(...),
    valor: float = Form(...),
    item_ids: list[str] = Form(default=[]),
):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    if not item_ids:
        request.session["flash"] = "Selecione ao menos um anúncio."
        return _redirect("/anuncios")
    atualizados, erros = 0, 0
    for iid in item_ids:
        try:
            meli.update_item(iid, _payload_massa(acao, valor, iid))
            atualizados += 1
        except Exception:  # noqa: BLE001
            logger.exception("Falha na edição em massa do item %s", iid)
            erros += 1
    if atualizados:
        _invalidar_cache_itens()
    msg = f"{atualizados} anúncio(s) atualizado(s)."
    if erros:
        msg += f" {erros} falharam."
    request.session["flash"] = msg
    return _redirect("/anuncios")


def _payload_massa(acao: str, valor: float, item_id: str) -> dict:
    """Monta o payload de atualização conforme a ação de edição em massa."""
    if acao == "estoque":
        return {"available_quantity": max(0, int(valor))}
    if acao == "preco":
        return {"price": round(valor, 2)}
    if acao in {"aumentar", "reduzir"}:
        atual = meli.get_item(item_id).get("price") or 0
        fator = 1 + (valor / 100) if acao == "aumentar" else 1 - (valor / 100)
        return {"price": round(atual * fator, 2)}
    raise ValueError(f"Ação inválida: {acao}")


@app.get("/anuncios/{item_id}/editar")
def editar_anuncio_form(request: Request, item_id: str):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    ctx = _base_context(request)
    try:
        ctx["item"] = meli.get_item(item_id)
        ctx["descricao"] = meli.get_item_description(item_id)
    except Exception as exc:  # noqa: BLE001
        request.session["flash"] = f"Não foi possível abrir o anúncio: {exc}"
        return _redirect("/anuncios")
    return templates.TemplateResponse(request, "editar_anuncio.html", ctx)


@app.post("/anuncios/{item_id}/editar")
async def editar_anuncio(
    request: Request,
    item_id: str,
    price: float = Form(...),
    available_quantity: int = Form(...),
    title: str = Form(""),
    description: str = Form(""),
    image_file: UploadFile = File(None),
):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    avisos: list[str] = []

    # 1) Preço, estoque e título (mesmo endpoint /items)
    payload: dict = {"price": price, "available_quantity": available_quantity}
    if title.strip():
        payload["title"] = title.strip()
    try:
        meli.update_item(item_id, payload)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao atualizar campos do anúncio")
        avisos.append(f"Preço/estoque/título: {exc}")

    # 2) Foto nova (opcional) — anexa às existentes
    if image_file is not None and image_file.filename:
        try:
            conteudo = await image_file.read()
            pic_id = meli.upload_picture(conteudo, image_file.filename, image_file.content_type)
            atuais = [{"id": p["id"]} for p in (meli.get_item(item_id).get("pictures") or []) if p.get("id")]
            atuais.append({"id": pic_id})
            meli.update_item(item_id, {"pictures": atuais})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha ao adicionar foto")
            avisos.append(f"Foto: {exc}")

    # 3) Descrição (endpoint próprio)
    if description.strip():
        try:
            meli.update_item_description(item_id, description.strip())
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha ao atualizar descrição")
            avisos.append(f"Descrição: {exc}")

    if avisos:
        request.session["flash"] = "Atualizado com avisos — " + " · ".join(avisos)
    else:
        request.session["flash"] = f"Anúncio {item_id} atualizado."
    _invalidar_cache_itens()
    logger.info("Anúncio %s atualizado (campos + fotos).", item_id)
    return _redirect("/anuncios")


@app.get("/anuncios/{item_id}/qualidade")
def qualidade_anuncio(request: Request, item_id: str):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    ctx = _base_context(request)
    try:
        item = meli.get_item(item_id)
        descricao = meli.get_item_description(item_id)
        try:
            attrs = meli.get_category_attributes(item.get("category_id", ""))
        except Exception:  # noqa: BLE001
            attrs = []
        ctx["item"] = item
        ctx["avaliacao"] = quality.evaluate(item, descricao, attrs)
    except Exception as exc:  # noqa: BLE001
        request.session["flash"] = f"Não foi possível avaliar o anúncio: {exc}"
        return _redirect("/anuncios")
    return templates.TemplateResponse(request, "qualidade.html", ctx)


@app.get("/anuncios/{item_id}/concorrencia")
def concorrencia_anuncio(request: Request, item_id: str):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    ctx = _base_context(request)
    ctx.update({"competidores": [], "resumo": None, "sugestao": None, "preco": 0,
                "recomendacao": None})
    try:
        item = meli.get_item(item_id)
        ctx["item"] = item
        preco = float(item.get("price") or 0)
        ctx["preco"] = preco
        catalog_id = item.get("catalog_product_id")

        if catalog_id:
            comps = meli.get_catalog_competitors(catalog_id)
            comps = sorted(comps, key=lambda c: c.get("price") or 0)
            ctx["competidores"] = comps
            precos = [float(c["price"]) for c in comps if c.get("price")]
            if precos:
                menor = min(precos)
                ctx["resumo"] = {
                    "menor": menor,
                    "maior": max(precos),
                    "media": round(sum(precos) / len(precos), 2),
                    "total": len(precos),
                    "mais_baratos": sum(1 for p in precos if p < preco),
                    "sou_menor": preco <= menor,
                    "diferenca_menor": round(preco - menor, 2),
                }
                if preco > menor:
                    ctx["recomendacao"] = {
                        "valor": round(menor, 2),
                        "motivo": f"Igualar o menor concorrente (R$ {menor:.2f}) para ganhar a compra.",
                    }
        else:
            sugestao = meli.get_price_suggestion(item_id) or None
            ctx["sugestao"] = sugestao
            ctx["recomendacao"] = _recomendacao_da_sugestao(sugestao, preco)
    except Exception as exc:  # noqa: BLE001
        ctx["error"] = f"Não foi possível carregar a concorrência: {exc}"
    return templates.TemplateResponse(request, "concorrencia.html", ctx)


def _recomendacao_da_sugestao(sugestao: dict | None, preco: float) -> dict | None:
    """Extrai um preço recomendado da sugestão do Mercado Livre, se houver."""
    if not sugestao:
        return None
    sp = sugestao.get("suggested_price") or {}
    valor = sp.get("amount") if isinstance(sp, dict) else sp
    if not valor:
        return None
    valor = round(float(valor), 2)
    if abs(valor - preco) < 0.01:
        return None
    return {"valor": valor, "motivo": "Preço sugerido pelo Mercado Livre para este produto."}


@app.post("/anuncios/{item_id}/preco")
def aplicar_preco(request: Request, item_id: str, price: float = Form(...)):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    try:
        meli.update_item(item_id, {"price": round(price, 2)})
        request.session["flash"] = f"Preço do anúncio {item_id} atualizado para R$ {price:.2f}."
        logger.info("Preço do anúncio %s atualizado para %.2f", item_id, price)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao aplicar preço recomendado")
        request.session["flash"] = f"Não foi possível atualizar o preço: {exc}"
    return _redirect(f"/anuncios/{item_id}/concorrencia")


# ---------------------------------------------------------------------------
# Vendas e entregas
# ---------------------------------------------------------------------------
@app.get("/vendas")
def vendas(request: Request, q: str = "", status: str = "", pagina: int = 1):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    ctx = _base_context(request)
    orders = []
    por_pagina = 30
    total = 0
    try:
        me = meli.get_me()
        todos = meli.list_all_orders(me["id"])

        termo = q.strip().lower()
        if termo:
            todos = [o for o in todos if _order_bate(o, termo)]
        if status:
            todos = [o for o in todos if o.get("status") == status]

        total = len(todos)
        pagina = max(1, pagina)
        inicio = (pagina - 1) * por_pagina
        orders = todos[inicio : inicio + por_pagina]
        for order in orders:
            ship = order.get("shipping") or {}
            ship_id = ship.get("id")
            if ship_id:
                try:
                    detail = meli.get_shipment(ship_id)
                    order["shipping_status"] = detail.get("status")
                    order["shipping_substatus"] = detail.get("substatus")
                except Exception:  # noqa: BLE001
                    order["shipping_status"] = None
    except Exception as exc:  # noqa: BLE001
        ctx["error"] = f"Não foi possível carregar as vendas: {exc}"
    total_paginas = max(1, (total + por_pagina - 1) // por_pagina)
    ctx.update({
        "orders": orders,
        "pagina": pagina,
        "total_paginas": total_paginas,
        "total_vendas": total,
        "q": q,
        "status_filtro": status,
    })
    return templates.TemplateResponse(request, "vendas.html", ctx)


def _order_bate(order: dict, termo: str) -> bool:
    """Verifica se um pedido corresponde ao termo de busca (id, comprador, produto)."""
    if termo in str(order.get("id", "")).lower():
        return True
    if termo in ((order.get("buyer") or {}).get("nickname") or "").lower():
        return True
    for item in order.get("order_items") or []:
        if termo in ((item.get("item") or {}).get("title") or "").lower():
            return True
    return False


def _csv_response(nome: str, cabecalho: list[str], linhas: list[list]) -> Response:
    """Monta uma resposta de download CSV (UTF-8 com BOM para Excel)."""
    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=";")
    escritor.writerow(cabecalho)
    escritor.writerows(linhas)
    conteudo = "\ufeff" + buffer.getvalue()
    return Response(
        content=conteudo,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


@app.get("/vendas/exportar")
def exportar_vendas(request: Request):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    linhas = []
    try:
        me = meli.get_me()
        for order in meli.list_all_orders(me["id"]):
            comprador = (order.get("buyer") or {}).get("nickname", "")
            itens = order.get("order_items") or []
            titulo = itens[0]["item"]["title"] if itens else ""
            qtd = sum(i.get("quantity", 0) for i in itens)
            linhas.append([
                (order.get("date_created") or "")[:10],
                order.get("id", ""),
                titulo,
                qtd,
                f"{order.get('total_amount', 0):.2f}",
                order.get("status", ""),
                comprador,
            ])
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao exportar vendas")
        request.session["flash"] = f"Não foi possível exportar as vendas: {exc}"
        return _redirect("/vendas")
    cabecalho = ["Data", "Pedido", "Produto", "Qtd", "Total (R$)", "Status", "Comprador"]
    return _csv_response("vendas.csv", cabecalho, linhas)



@app.get("/vendas/{order_id}/mensagens")
def mensagens_form(request: Request, order_id: str):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    ctx = _base_context(request)
    ctx.update({"order_id": order_id, "messages": [], "pack_id": order_id,
                "buyer_id": None, "seller_id": None,
                "respostas": database.list_quick_replies()})
    try:
        me = meli.get_me()
        ctx["seller_id"] = me["id"]
        order = meli.get_order(order_id)
        pack_id = order.get("pack_id") or order_id
        ctx["pack_id"] = pack_id
        ctx["buyer_id"] = (order.get("buyer") or {}).get("id")
        msgs = meli.get_pack_messages(pack_id, me["id"])
        ctx["messages"] = msgs.get("messages", [])
    except Exception as exc:  # noqa: BLE001
        ctx["error"] = f"Não foi possível carregar as mensagens: {exc}"
    return templates.TemplateResponse(request, "mensagens.html", ctx)


@app.post("/vendas/{order_id}/mensagens")
def enviar_mensagem(
    request: Request,
    order_id: str,
    pack_id: str = Form(...),
    buyer_id: int = Form(...),
    text: str = Form(...),
):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    try:
        me = meli.get_me()
        meli.send_pack_message(pack_id, me["id"], buyer_id, text.strip())
        request.session["flash"] = "Mensagem enviada."
        logger.info("Mensagem enviada no pedido %s.", order_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao enviar mensagem")
        request.session["flash"] = f"Não foi possível enviar a mensagem: {exc}"
    return _redirect(f"/vendas/{order_id}/mensagens")


# ---------------------------------------------------------------------------
# Pós-venda (perguntas + reclamações)
# ---------------------------------------------------------------------------
@app.get("/pos-venda")
def pos_venda(request: Request):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    respostas = database.list_quick_replies()
    ctx = _base_context(request)
    ctx.update({"questions": [], "claims": [], "avisos": [], "respostas": respostas})
    try:
        me = meli.get_me()
        try:
            q = meli.search_questions(me["id"])
            perguntas = q.get("questions", [])
            for pergunta in perguntas:
                pergunta["sugestao"] = _sugerir_resposta(
                    pergunta.get("text", ""), respostas
                )
            ctx["questions"] = perguntas
        except Exception as exc:  # noqa: BLE001
            ctx["avisos"].append(f"Perguntas indisponíveis: {exc}")
        try:
            c = meli.search_claims()
            ctx["claims"] = c.get("data", c.get("results", []))
        except Exception as exc:  # noqa: BLE001
            ctx["avisos"].append(f"Reclamações indisponíveis: {exc}")
    except Exception as exc:  # noqa: BLE001
        ctx["error"] = f"Não foi possível carregar o pós-venda: {exc}"
    return templates.TemplateResponse(request, "pos_venda.html", ctx)


_STOPWORDS = {
    "de", "da", "do", "das", "dos", "que", "para", "com", "uma", "por", "não",
    "nao", "meu", "minha", "voce", "você", "vcs", "tem", "esse", "essa", "este",
    "esta", "como", "qual", "quanto", "seu", "sua", "isso", "ola", "olá", "boa",
    "bom", "dia", "tarde", "noite", "obrigado", "obrigada", "gostaria", "saber",
}


def _tokens(texto: str) -> set[str]:
    return {
        t
        for t in re.findall(r"[a-zà-ú0-9]+", texto.lower())
        if len(t) > 2 and t not in _STOPWORDS
    }


def _sugerir_resposta(pergunta: str, respostas: list[dict]) -> str:
    """Sugere o texto da resposta rápida mais parecida com a pergunta."""
    tokens_p = _tokens(pergunta)
    if not tokens_p or not respostas:
        return ""
    melhor, score = "", 0
    for r in respostas:
        n = len(tokens_p & _tokens(f"{r['titulo']} {r['texto']}"))
        if n > score:
            score, melhor = n, r["texto"]
    return melhor if score >= 1 else ""


@app.post("/pos-venda/responder")
def responder_pergunta(
    request: Request, question_id: int = Form(...), text: str = Form(...)
):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    try:
        meli.answer_question(question_id, text.strip())
        request.session["flash"] = "Resposta enviada."
        logger.info("Pergunta %s respondida.", question_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao responder pergunta")
        request.session["flash"] = f"Não foi possível responder: {exc}"
    return _redirect("/pos-venda")


@app.post("/pos-venda/responder-massa")
def responder_perguntas_massa(
    request: Request,
    text: str = Form(...),
    question_ids: list[int] = Form(default=[]),
):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    texto = text.strip()
    if not question_ids or not texto:
        request.session["flash"] = "Selecione perguntas e escreva a resposta."
        return _redirect("/pos-venda")
    respondidas, erros = 0, 0
    for qid in question_ids:
        try:
            meli.answer_question(qid, texto)
            respondidas += 1
        except Exception:  # noqa: BLE001
            logger.exception("Falha ao responder pergunta %s em massa", qid)
            erros += 1
    msg = f"{respondidas} pergunta(s) respondida(s)."
    if erros:
        msg += f" {erros} falharam."
    request.session["flash"] = msg
    return _redirect("/pos-venda")


# ---------------------------------------------------------------------------
# Estatísticas (visitas)
# ---------------------------------------------------------------------------
@app.get("/estatisticas")
def estatisticas(request: Request):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    ctx = _base_context(request)
    linhas = []
    try:
        me = meli.get_me()
        ids = meli.list_item_ids(me["id"], limit=20)
        items = meli.get_items_details(ids)
        for it in items:
            visits = 0
            try:
                v = meli.get_item_visits(it["id"])
                visits = v.get(it["id"], 0) if isinstance(v, dict) else 0
            except Exception:  # noqa: BLE001
                visits = 0
            sold = it.get("sold_quantity", 0)
            conversao = round(100 * sold / visits, 1) if visits else None
            linhas.append(
                {
                    "id": it.get("id"),
                    "title": it.get("title"),
                    "visits": visits,
                    "sold": sold,
                    "conversao": conversao,
                }
            )
    except Exception as exc:  # noqa: BLE001
        ctx["error"] = f"Não foi possível carregar as estatísticas: {exc}"
    ctx["linhas"] = linhas
    return templates.TemplateResponse(request, "estatisticas.html", ctx)


# ---------------------------------------------------------------------------
# Lucratividade (comissões reais das vendas)
# ---------------------------------------------------------------------------
@app.get("/lucratividade")
def lucratividade(request: Request):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    ctx = _base_context(request)
    linhas = []
    totais = {"bruto": 0.0, "comissao": 0.0, "liquido": 0.0}
    try:
        me = meli.get_me()
        orders = meli.search_orders(me["id"], limit=50)
        for order in orders:
            bruto = float(order.get("total_amount") or 0)
            comissao = sum(
                float(item.get("sale_fee") or 0)
                for item in order.get("order_items", [])
            )
            liquido = bruto - comissao
            totais["bruto"] += bruto
            totais["comissao"] += comissao
            totais["liquido"] += liquido
            linhas.append(
                {
                    "id": order.get("id"),
                    "data": (order.get("date_created") or "")[:10],
                    "bruto": bruto,
                    "comissao": comissao,
                    "liquido": liquido,
                }
            )
    except Exception as exc:  # noqa: BLE001
        ctx["error"] = f"Não foi possível carregar a lucratividade: {exc}"
    ctx["linhas"] = linhas
    ctx["totais"] = totais
    return templates.TemplateResponse(request, "lucratividade.html", ctx)


@app.get("/lucratividade/exportar")
def exportar_lucratividade(request: Request):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    linhas = []
    try:
        me = meli.get_me()
        for order in meli.list_all_orders(me["id"]):
            bruto = float(order.get("total_amount") or 0)
            comissao = sum(
                float(item.get("sale_fee") or 0)
                for item in order.get("order_items", [])
            )
            linhas.append([
                (order.get("date_created") or "")[:10],
                order.get("id", ""),
                f"{bruto:.2f}",
                f"{comissao:.2f}",
                f"{bruto - comissao:.2f}",
            ])
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao exportar lucratividade")
        request.session["flash"] = f"Não foi possível exportar: {exc}"
        return _redirect("/lucratividade")
    cabecalho = ["Data", "Pedido", "Bruto (R$)", "Comissão (R$)", "Líquido (R$)"]
    return _csv_response("lucratividade.csv", cabecalho, linhas)


# ---------------------------------------------------------------------------
# Tendências (palavras-chave em alta)
# ---------------------------------------------------------------------------
@app.get("/tendencias")
def tendencias(request: Request, categoria: str = "", termo: str = "", atualizar: int = 0):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    ctx = _base_context(request)
    trends, categorias, categoria_nome, cache_em = [], [], "", None
    termo = termo.strip()
    force = bool(atualizar)
    try:
        me, _ = _me_cached(force=force)
        uid = me["id"]
        chave_cat = f"tend_categorias:{uid}"
        cached_cat = _cache_ler(chave_cat, force=force)
        if cached_cat:
            categorias, quando_cat = cached_cat
        else:
            ids = meli.list_all_item_ids(uid)
            items = meli.get_items_details(ids)
            cat_ids = sorted({it.get("category_id") for it in items if it.get("category_id")})
            categorias = [{"id": c, "nome": meli.get_category_name(c)} for c in cat_ids]
            quando_cat = _cache_gravar(chave_cat, categorias)

        if termo:
            previsao = meli.predict_category(termo)
            categoria = previsao.get("category_id", "")
            categoria_nome = previsao.get("category_name", "")
            if not categoria:
                ctx["aviso"] = f"Não encontramos categoria para “{termo}”. Mostrando tendências gerais."
        elif categoria:
            categoria_nome = meli.get_category_name(categoria)

        chave_tr = f"tend_trends:{categoria}"
        cached_tr = _cache_ler(chave_tr, force=force)
        if cached_tr:
            trends, quando_tr = cached_tr
        else:
            trends = meli.get_trends(categoria)
            quando_tr = _cache_gravar(chave_tr, trends)
        cache_em = min(quando_cat, quando_tr)
    except Exception as exc:  # noqa: BLE001
        ctx["error"] = f"Não foi possível carregar as tendências: {exc}"
    ctx.update({
        "trends": trends,
        "categorias": categorias,
        "categoria": categoria,
        "categoria_nome": categoria_nome,
        "termo": termo,
        "cache_em": cache_em,
    })
    return templates.TemplateResponse(request, "tendencias.html", ctx)


@app.get("/historico")
def historico(request: Request):
    if not _current_user_id(request):
        return _redirect("/entrar")
    ctx = _base_context(request)
    snaps = database.list_snapshots()
    ctx["snapshots"] = snaps
    max_fat = max((s["faturamento"] or 0) for s in snaps) if snaps else 0
    ctx["max_faturamento"] = max_fat or 1
    return templates.TemplateResponse(request, "historico.html", ctx)


# ---------------------------------------------------------------------------
# Promoções e descontos
# ---------------------------------------------------------------------------
@app.get("/promocoes")
def promocoes(request: Request, atualizar: int = 0):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    ctx = _base_context(request)
    ctx.update({"campanhas": [], "items": [], "cache_em": None})
    force = bool(atualizar)
    try:
        me, _ = _me_cached(force=force)
        chave = f"promocoes:{me['id']}"
        cached = _cache_ler(chave, force=force)
        if cached:
            dados, ctx["cache_em"] = cached
            ctx["campanhas"] = dados.get("campanhas", [])
            ctx["items"] = dados.get("items", [])
        else:
            campanhas = meli.get_seller_promotions(me["id"])
            ids = meli.list_all_item_ids(me["id"])
            items = meli.get_items_details(ids)
            ctx["campanhas"] = campanhas
            ctx["items"] = items
            ctx["cache_em"] = _cache_gravar(
                chave, {"campanhas": campanhas, "items": items}
            )
    except Exception as exc:  # noqa: BLE001
        ctx["error"] = f"Não foi possível carregar as promoções: {exc}"
    return templates.TemplateResponse(request, "promocoes.html", ctx)


@app.get("/promocoes/{item_id}")
def promocoes_item(request: Request, item_id: str):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    ctx = _base_context(request)
    ctx.update({"item": None, "ofertas": []})
    try:
        ctx["item"] = meli.get_item(item_id)
        ctx["ofertas"] = meli.get_item_promotions(item_id)
    except Exception as exc:  # noqa: BLE001
        ctx["error"] = f"Não foi possível carregar as ofertas: {exc}"
    return templates.TemplateResponse(request, "promocoes_item.html", ctx)


@app.post("/promocoes/{item_id}/aplicar")
def promocoes_aplicar(
    request: Request,
    item_id: str,
    promotion_id: str = Form(...),
    promotion_type: str = Form(...),
    deal_price: float = Form(...),
):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    try:
        meli.apply_item_promotion(item_id, promotion_id, promotion_type, deal_price)
        _invalidar_cache_itens()
        request.session["flash"] = f"Promoção aplicada ao anúncio {item_id}."
        logger.info("Promoção %s aplicada em %s", promotion_id, item_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao aplicar promoção")
        request.session["flash"] = f"Não foi possível aplicar a promoção: {exc}"
    return _redirect(f"/promocoes/{item_id}")


@app.post("/promocoes/{item_id}/remover")
def promocoes_remover(
    request: Request,
    item_id: str,
    promotion_id: str = Form(...),
    promotion_type: str = Form(...),
):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    try:
        meli.remove_item_promotion(item_id, promotion_id, promotion_type)
        _invalidar_cache_itens()
        request.session["flash"] = f"Promoção removida do anúncio {item_id}."
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao remover promoção")
        request.session["flash"] = f"Não foi possível remover a promoção: {exc}"
    return _redirect(f"/promocoes/{item_id}")


# ---------------------------------------------------------------------------
# Agendamento de ações
# ---------------------------------------------------------------------------
@app.get("/agendamentos")
def agendamentos(request: Request):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    ctx = _base_context(request)
    ctx.update({"tasks": database.list_tasks(), "items": []})
    try:
        me = meli.get_me()
        ids = meli.list_all_item_ids(me["id"])
        ctx["items"] = meli.get_items_details(ids)
    except Exception as exc:  # noqa: BLE001
        ctx["error"] = f"Não foi possível carregar os anúncios: {exc}"
    return templates.TemplateResponse(request, "agendamentos.html", ctx)


@app.post("/agendamentos")
def agendamentos_criar(
    request: Request,
    tipo: str = Form(...),
    item_id: str = Form(...),
    quando: str = Form(...),
    valor: float = Form(0),
):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    try:
        executar_em = int(datetime.fromisoformat(quando).timestamp())
    except ValueError:
        request.session["flash"] = "Data/hora inválida."
        return _redirect("/agendamentos")
    if executar_em <= int(datetime.now().timestamp()):
        request.session["flash"] = "Escolha uma data/hora no futuro."
        return _redirect("/agendamentos")
    titulo = ""
    try:
        titulo = meli.get_item(item_id).get("title", "")
    except Exception:  # noqa: BLE001
        pass
    database.add_task(tipo, item_id, executar_em, titulo,
                      valor if tipo == "preco" else None)
    request.session["flash"] = "Ação agendada com sucesso."
    return _redirect("/agendamentos")


@app.post("/agendamentos/{task_id}/cancelar")
def agendamentos_cancelar(request: Request, task_id: int):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    database.cancel_task(task_id)
    request.session["flash"] = "Agendamento cancelado."
    return _redirect("/agendamentos")


# ---------------------------------------------------------------------------
# Respostas rápidas (templates de mensagens)
# ---------------------------------------------------------------------------
@app.get("/respostas")
def respostas_form(request: Request):
    if not _current_user_id(request):
        return _redirect("/entrar")
    ctx = _base_context(request)
    ctx["respostas"] = database.list_quick_replies()
    return templates.TemplateResponse(request, "respostas.html", ctx)


@app.post("/respostas")
def respostas_add(request: Request, titulo: str = Form(...), texto: str = Form(...)):
    if not _current_user_id(request):
        return _redirect("/entrar")
    if titulo.strip() and texto.strip():
        database.add_quick_reply(titulo.strip(), texto.strip())
        request.session["flash"] = "Resposta rápida salva."
    return _redirect("/respostas")


@app.post("/respostas/{reply_id}/excluir")
def respostas_delete(request: Request, reply_id: int):
    if not _current_user_id(request):
        return _redirect("/entrar")
    database.delete_quick_reply(reply_id)
    request.session["flash"] = "Resposta rápida excluída."
    return _redirect("/respostas")

