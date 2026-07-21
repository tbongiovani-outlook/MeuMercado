"""Aplicação FastAPI — Meu Mercado.

Fluxo de uso (fácil para o usuário final, roda em Windows e macOS):
  1. Primeiro acesso  -> cria a conta local (usuário + senha com hash de mão única)
  2. Login local      -> entra com usuário e senha
  3. Configuração     -> informa o Client ID / Secret do Mercado Livre
  4. Conectar         -> autoriza no Mercado Livre (OAuth) e vê os dados
"""

import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import auth, database, meli, telemetry
from .config import settings

# Configura logging em arquivo assim que o módulo é importado.
logger = telemetry.setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    logger.info("Aplicação iniciada. Banco pronto em %s", settings.database_path)
    yield
    logger.info("Aplicação finalizada.")


app = FastAPI(title="Meu Mercado", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.app_secret_key)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Instrumenta a aplicação com OpenTelemetry.
telemetry.setup_telemetry(app)


def _current_user_id(request: Request):
    return request.session.get("user_id")


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


# ---------------------------------------------------------------------------
# Painel principal
# ---------------------------------------------------------------------------
@app.get("/")
def home(request: Request):
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
        "items": [],
        "orders": [],
        "error": request.session.pop("flash", None),
    }

    if context["configured"] and context["connected"]:
        try:
            context["ml_user"] = meli.api_get("/users/me")
        except Exception as exc:  # noqa: BLE001
            context["error"] = f"Não foi possível ler os dados da conta: {exc}"

        ml_user = context["ml_user"]
        avisos = []
        if ml_user:
            try:
                items = meli.api_get(
                    f"/users/{ml_user['id']}/items/search", {"limit": 20}
                )
                context["items"] = items.get("results", [])
            except Exception as exc:  # noqa: BLE001
                avisos.append(
                    "Não foi possível ler os anúncios — habilite a permissão "
                    "\"Publicação e sincronização\" no seu app do Mercado Livre "
                    "e reconecte. "
                    f"(detalhe: {exc})"
                )
            try:
                orders = meli.api_get(
                    "/orders/search", {"seller": ml_user["id"], "sort": "date_desc"}
                )
                context["orders"] = orders.get("results", [])
            except Exception as exc:  # noqa: BLE001
                avisos.append(
                    "Não foi possível ler as vendas — verifique a permissão de "
                    "vendas/pedidos no seu app do Mercado Livre e reconecte. "
                    f"(detalhe: {exc})"
                )

        if avisos and not context["error"]:
            context["error"] = " · ".join(avisos)

    return templates.TemplateResponse(request, "dashboard.html", context)


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
    context = {
        "error": None,
        "saved": False,
        "client_id": meli.get_client_id(),
        "has_secret": bool(meli.get_client_secret()),
        "redirect_uri": meli.get_redirect_uri(),
    }
    return templates.TemplateResponse(request, "configuracao.html", context)


@app.post("/configuracao")
def configuracao_save(
    request: Request,
    client_id: str = Form(""),
    client_secret: str = Form(""),
    redirect_uri: str = Form(""),
):
    if not _current_user_id(request):
        return _redirect("/entrar")

    database.set_config("meli_client_id", client_id.strip())
    database.set_config("meli_redirect_uri", redirect_uri.strip())
    # Só sobrescreve o secret se o usuário digitou um novo (mantém o atual se vazio).
    if client_secret.strip():
        database.set_config("meli_client_secret", client_secret.strip())

    context = {
        "error": None,
        "saved": True,
        "client_id": meli.get_client_id(),
        "has_secret": bool(meli.get_client_secret()),
        "redirect_uri": meli.get_redirect_uri(),
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
def anuncios(request: Request):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    ctx = _base_context(request)
    items = []
    try:
        me = meli.get_me()
        ids = meli.list_item_ids(me["id"], limit=50)
        items = meli.get_items_details(ids)
    except Exception as exc:  # noqa: BLE001
        ctx["error"] = f"Não foi possível carregar os anúncios: {exc}"
    ctx["items"] = items
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
        rotulos = {"active": "reativado", "paused": "pausado", "closed": "encerrado"}
        request.session["flash"] = f"Anúncio {item_id} {rotulos[status]}."
        logger.info("Anúncio %s alterado para %s", item_id, status)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao alterar status do anúncio")
        request.session["flash"] = f"Não foi possível alterar o anúncio: {exc}"
    return _redirect("/anuncios")


@app.get("/anuncios/{item_id}/editar")
def editar_anuncio_form(request: Request, item_id: str):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    ctx = _base_context(request)
    try:
        ctx["item"] = meli.get_item(item_id)
    except Exception as exc:  # noqa: BLE001
        request.session["flash"] = f"Não foi possível abrir o anúncio: {exc}"
        return _redirect("/anuncios")
    return templates.TemplateResponse(request, "editar_anuncio.html", ctx)


@app.post("/anuncios/{item_id}/editar")
def editar_anuncio(
    request: Request,
    item_id: str,
    price: float = Form(...),
    available_quantity: int = Form(...),
):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    try:
        meli.update_item(
            item_id, {"price": price, "available_quantity": available_quantity}
        )
        request.session["flash"] = f"Anúncio {item_id} atualizado."
        logger.info("Anúncio %s atualizado (preço/estoque).", item_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao atualizar anúncio")
        request.session["flash"] = f"Não foi possível atualizar o anúncio: {exc}"
    return _redirect("/anuncios")


# ---------------------------------------------------------------------------
# Vendas e entregas
# ---------------------------------------------------------------------------
@app.get("/vendas")
def vendas(request: Request):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    ctx = _base_context(request)
    orders = []
    try:
        me = meli.get_me()
        orders = meli.search_orders(me["id"], limit=30)
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
    ctx["orders"] = orders
    return templates.TemplateResponse(request, "vendas.html", ctx)


# ---------------------------------------------------------------------------
# Pós-venda (perguntas + reclamações)
# ---------------------------------------------------------------------------
@app.get("/pos-venda")
def pos_venda(request: Request):
    redirect, _ = _require_ready(request)
    if redirect:
        return redirect
    ctx = _base_context(request)
    ctx.update({"questions": [], "claims": [], "avisos": []})
    try:
        me = meli.get_me()
        try:
            q = meli.search_questions(me["id"])
            ctx["questions"] = q.get("questions", [])
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
            linhas.append(
                {
                    "id": it.get("id"),
                    "title": it.get("title"),
                    "visits": visits,
                    "sold": it.get("sold_quantity", 0),
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

