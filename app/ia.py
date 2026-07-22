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
DEFAULT_MODELO = "qwen2.5:3b"

_SYSTEM = (
    "Você é um vendedor do Mercado Livre respondendo a um cliente em português do "
    "Brasil. Escreva uma resposta curta, cordial e objetiva à pergunta, sem saudações "
    "longas e sem prometer o que não pode cumprir. Responda apenas com o texto da "
    "mensagem, sem aspas."
)

_SYSTEM_DESCRICAO = (
    "Você é um vendedor do Mercado Livre escrevendo a descrição de um anúncio em "
    "português do Brasil. Estruture a resposta em três partes, nesta ordem: "
    "(1) 2 a 3 parágrafos curtos e persuasivos destacando benefícios e usos do produto; "
    "(2) uma seção começando com a linha 'Especificações técnicas:' seguida de uma lista "
    "com um item por linha começando por '- ' (ex.: marca, modelo, material, capacidade, "
    "dimensões, cor, itens inclusos) inferidos a partir do título; "
    "(3) uma última linha com 5 a 8 hashtags relevantes para a busca, começando com '#' e "
    "separadas por espaço. Não invente preço, garantia nem prazo de entrega e não inclua "
    "links, telefone, e-mail nem nome de outras lojas. Responda apenas com o texto da descrição."
)

_SYSTEM_RECLAMACAO = (
    "Você é um vendedor do Mercado Livre respondendo a uma reclamação de um cliente em "
    "português do Brasil. Seja empático, profissional e objetivo: reconheça o problema, "
    "ofereça um encaminhamento (troca, reembolso ou orientação) e mantenha um tom cordial. "
    "Não admita culpa jurídica nem prometa o que não pode cumprir. Responda apenas com o "
    "texto da mensagem, sem aspas."
)

_SYSTEM_RESUMO = (
    "Você é um assistente que resume o dia de um vendedor do Mercado Livre em português "
    "do Brasil. A partir dos indicadores fornecidos, escreva um resumo curto (2 a 4 frases) "
    "em linguagem natural, destacando o que precisa de atenção. Responda apenas com o resumo."
)

_SYSTEM_TITULO = (
    "Você é um especialista em anúncios do Mercado Livre. Reescreva o título do anúncio em "
    "português do Brasil para ser mais atraente e fácil de encontrar na busca, com marca, "
    "modelo e as principais características. O título deve ser CURTO e direto, com no máximo "
    "60 caracteres (cerca de 8 a 10 palavras) — não ultrapasse esse limite. Sem CAIXA ALTA "
    "excessiva, sem emojis e sem frases promocionais longas. Responda apenas com o título."
)

_SYSTEM_VARIACAO = (
    "Você é um vendedor do Mercado Livre. Reescreva a mensagem a seguir mantendo o mesmo "
    "sentido, em português do Brasil, com um tom cordial e natural, um pouco diferente do "
    "original. Responda apenas com o novo texto, sem aspas."
)

_SYSTEM_ASSISTENTE = (
    "Você é um assistente que ajuda vendedores do Mercado Livre no Brasil. Responda de "
    "forma prática e objetiva, em português do Brasil. Quando listar dicas ou passos, use "
    "uma lista com marcadores, com um item por linha começando por '- '. Separe parágrafos "
    "com uma linha em branco. Destaque termos importantes com **negrito**. Seja conciso: no "
    "máximo 6 itens ou 2 parágrafos curtos."
)


def habilitada() -> bool:
    """True se o usuário ligou a integração de IA nas configurações."""
    return (database.get_config("ia_habilitada") or "") == "1"


def endpoint() -> str:
    """Endereço base do Ollama, sem barra final."""
    return (database.get_config("ia_endpoint") or DEFAULT_ENDPOINT).rstrip("/")


def modelo() -> str:
    """Nome do modelo a usar (ex.: ``qwen2.5:3b``)."""
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
    return _gerar(_SYSTEM, prompt, timeout=timeout)


def gerar_descricao(titulo: str, marca: str = "", timeout: float = 90.0) -> str:
    """Gera a descrição de um anúncio a partir do título (e marca). '' em falha."""
    titulo = (titulo or "").strip()
    if not titulo or not habilitada():
        return ""
    prompt = f"Título do anúncio: {titulo}\n"
    if marca.strip():
        prompt += f"Marca: {marca.strip()}\n"
    prompt += "Descrição sugerida:"
    return _gerar(_SYSTEM_DESCRICAO, prompt, timeout=timeout, num_predict=550)


def sugerir_reclamacao(texto: str, timeout: float = 30.0) -> str:
    """Gera uma resposta cordial a uma reclamação do pós-venda. '' em falha."""
    texto = (texto or "").strip()
    if not texto or not habilitada():
        return ""
    prompt = f"Reclamação do cliente: {texto}\nResposta sugerida:"
    return _gerar(_SYSTEM_RECLAMACAO, prompt, timeout=timeout)


def resumo_do_dia(kpis: dict, timeout: float = 30.0) -> str:
    """Gera um resumo em linguagem natural a partir dos indicadores do painel."""
    if not kpis or not habilitada():
        return ""
    linhas = "\n".join(f"- {chave}: {valor}" for chave, valor in kpis.items())
    prompt = f"Indicadores de hoje:\n{linhas}\nResumo:"
    return _gerar(_SYSTEM_RESUMO, prompt, timeout=timeout)


# Conectores/pontuação que não devem sobrar soltos no fim de um título truncado.
_TITULO_CONECTORES = {
    "de",
    "da",
    "do",
    "das",
    "dos",
    "com",
    "e",
    "para",
    "por",
    "em",
    "a",
    "o",
    "no",
    "na",
    "nos",
    "nas",
    "ao",
    "à",
    "-",
    "–",
    "+",
    "/",
}


def _titulo_ajustado(texto: str) -> str:
    """Limita a 60 caracteres sem cortar palavra e remove conectores soltos no fim."""
    t = (texto or "").strip().strip('"').strip()
    if len(t) > 60:
        corte = t[:60]
        if " " in corte:
            corte = corte.rsplit(" ", 1)[0]
        t = corte
    partes = t.rstrip(" ,;:.-–").split(" ")
    while partes and partes[-1].lower() in _TITULO_CONECTORES:
        partes.pop()
    return " ".join(partes).rstrip(" ,;:.-–").strip()


def melhorar_titulo(titulo: str, marca: str = "", timeout: float = 30.0) -> str:
    """Reescreve o título do anúncio para ser mais vendável (SEO). '' em falha."""
    titulo = (titulo or "").strip()
    if not titulo or not habilitada():
        return ""
    prompt = f"Título atual: {titulo}\n"
    if marca.strip():
        prompt += f"Marca: {marca.strip()}\n"
    prompt += "Novo título:"
    novo = _gerar(_SYSTEM_TITULO, prompt, timeout=timeout, num_predict=80)
    return _titulo_ajustado(novo)


def variar_resposta(texto: str, timeout: float = 30.0) -> str:
    """Reescreve uma resposta rápida gerando uma variação. '' em falha."""
    texto = (texto or "").strip()
    if not texto or not habilitada():
        return ""
    prompt = f"Mensagem original: {texto}\nNova versão:"
    return _gerar(_SYSTEM_VARIACAO, prompt, timeout=timeout)


def assistente(pergunta: str, timeout: float = 60.0) -> str:
    """Responde a uma dúvida livre sobre vender no Mercado Livre. '' em falha."""
    pergunta = (pergunta or "").strip()
    if not pergunta or not habilitada():
        return ""
    prompt = f"Pergunta: {pergunta}\nResposta:"
    return _gerar(_SYSTEM_ASSISTENTE, prompt, timeout=timeout, num_predict=300)


def _gerar(system: str, prompt: str, timeout: float = 30.0, num_predict: int = 200) -> str:
    """Chama o modelo local (Ollama ``/api/generate``). Retorna '' em qualquer falha."""
    if not habilitada():
        return ""
    try:
        resp = httpx.post(
            f"{endpoint()}/api/generate",
            json={
                "model": modelo(),
                "system": system,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": num_predict},
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return (resp.json().get("response") or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("IA local indisponível: %s", exc)
        return ""
