"""Integração opcional de IA local (Ollama) para sugerir respostas.

Conversa com um servidor Ollama local via HTTP (padrão ``http://localhost:11434``)
usando o ``httpx`` que já é dependência do projeto — nenhuma lib nova. Tudo degrada
com segurança: se a integração estiver desligada nas configurações ou o Ollama não
estiver rodando, as funções retornam vazio/``False`` sem lançar exceção.

Multiplataforma (Windows/macOS) e 100% local: os dados do cliente não saem da máquina.
"""

import logging

import httpx

from . import database

logger = logging.getLogger("meu_mercado")

DEFAULT_ENDPOINT = "http://localhost:11434"
DEFAULT_MODELO = "llama3.2:3b"

_SYSTEM = (
    "Você é um vendedor do Mercado Livre respondendo a um cliente em português do "
    "Brasil. Escreva uma resposta curta, cordial e objetiva à pergunta, sem saudações "
    "longas e sem prometer o que não pode cumprir. Responda apenas com o texto da "
    "mensagem, sem aspas."
)


def habilitada() -> bool:
    """True se o usuário ligou a integração de IA nas configurações."""
    return (database.get_config("ia_habilitada") or "") == "1"


def endpoint() -> str:
    """Endereço base do Ollama, sem barra final."""
    return (database.get_config("ia_endpoint") or DEFAULT_ENDPOINT).rstrip("/")


def modelo() -> str:
    """Nome do modelo a usar (ex.: ``llama3.2:3b``)."""
    return database.get_config("ia_modelo") or DEFAULT_MODELO


def disponivel(timeout: float = 1.5) -> bool:
    """True se a IA está habilitada E o Ollama responde localmente."""
    if not habilitada():
        return False
    try:
        resp = httpx.get(f"{endpoint()}/api/tags", timeout=timeout)
        return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def sugerir_resposta(pergunta: str, contexto: str = "", timeout: float = 30.0) -> str:
    """Gera uma sugestão de resposta com o modelo local. Retorna '' em falha."""
    pergunta = (pergunta or "").strip()
    if not pergunta or not habilitada():
        return ""

    prompt = f"Pergunta do cliente: {pergunta}\n"
    if contexto:
        prompt += f"Contexto do anúncio: {contexto}\n"
    prompt += "Resposta sugerida:"

    try:
        resp = httpx.post(
            f"{endpoint()}/api/generate",
            json={
                "model": modelo(),
                "system": _SYSTEM,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 200},
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return (resp.json().get("response") or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Sugestão de IA indisponível: %s", exc)
        return ""
