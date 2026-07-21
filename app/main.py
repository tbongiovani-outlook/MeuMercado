"""Aplicação FastAPI — Meu Mercado.

Fluxo de uso (fácil para o usuário final, roda em Windows e macOS):
  1. Primeiro acesso  -> cria a conta local (usuário + senha com hash de mão única)
  2. Login local      -> entra com usuário e senha
  3. Configuração     -> informa o Client ID / Secret do Mercado Livre
  4. Conectar         -> autoriza no Mercado Livre (OAuth) e vê os dados
"""

import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import auth, database, meli
from .config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield


app = FastAPI(title="Meu Mercado", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.app_secret_key)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


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
            ml_user = meli.api_get("/users/me")
            context["ml_user"] = ml_user
            items = meli.api_get(
                f"/users/{ml_user['id']}/items/search", {"limit": 20}
            )
            context["items"] = items.get("results", [])
            orders = meli.api_get(
                "/orders/search", {"seller": ml_user["id"], "sort": "date_desc"}
            )
            context["orders"] = orders.get("results", [])
        except Exception as exc:  # noqa: BLE001 - exibimos o erro na tela
            context["error"] = str(exc)

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
    request.session["oauth_state"] = state
    return RedirectResponse(meli.build_authorization_url(state))


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

    try:
        meli.exchange_code(code)
    except Exception as exc:  # noqa: BLE001
        request.session["flash"] = f"Falha ao conectar ao Mercado Livre: {exc}"
        return _redirect("/")

    request.session.pop("oauth_state", None)
    return _redirect("/")


@app.get("/mercadolivre/desconectar")
def ml_desconectar(request: Request):
    if not _current_user_id(request):
        return _redirect("/entrar")
    database.clear_tokens()
    request.session["flash"] = "Conta do Mercado Livre desconectada."
    return _redirect("/")
