"""Aplicação FastAPI — Meu Mercado.

Fluxo:
  /            -> painel (se autenticado) ou tela de login
  /login       -> redireciona ao consentimento do Mercado Livre (OAuth)
  /callback    -> troca o code por token e salva
  /logout      -> remove o token local
"""

import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import database, meli
from .config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield


app = FastAPI(title="Meu Mercado", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.app_secret_key)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/")
def home(request: Request):
    token = database.get_token()
    if not token:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "configured": settings.is_configured, "error": None},
        )

    context = {
        "request": request,
        "user": None,
        "items": [],
        "orders": [],
        "error": None,
    }
    try:
        user = meli.api_get("/users/me")
        context["user"] = user
        items = meli.api_get(f"/users/{user['id']}/items/search", {"limit": 20})
        context["items"] = items.get("results", [])
        orders = meli.api_get(
            "/orders/search", {"seller": user["id"], "sort": "date_desc"}
        )
        context["orders"] = orders.get("results", [])
    except Exception as exc:  # noqa: BLE001 - exibimos o erro na tela
        context["error"] = str(exc)

    return templates.TemplateResponse("dashboard.html", context)


@app.get("/login")
def login(request: Request):
    if not settings.is_configured:
        return RedirectResponse("/")
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
    if error:
        return _login_error(request, f"Autorização negada: {error}")

    expected = request.session.get("oauth_state")
    if not state or state != expected:
        return _login_error(request, "Parâmetro 'state' inválido (possível CSRF).")

    if not code:
        return RedirectResponse("/")

    try:
        meli.exchange_code(code)
    except Exception as exc:  # noqa: BLE001
        return _login_error(request, f"Falha ao trocar o code por token: {exc}")

    request.session.pop("oauth_state", None)
    return RedirectResponse("/")


@app.get("/logout")
def logout(request: Request):
    database.clear_tokens()
    request.session.clear()
    return RedirectResponse("/")


def _login_error(request: Request, message: str):
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "configured": settings.is_configured, "error": message},
    )
