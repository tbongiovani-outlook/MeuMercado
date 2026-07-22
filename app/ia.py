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

_SYSTEM_DESCRICAO = (
    "Você é um vendedor do Mercado Livre escrevendo a descrição de um anúncio em "
    "português do Brasil. Escreva uma descrição clara e persuasiva em 2 a 4 parágrafos "
    "curtos, destacando benefícios e características do produto. NÃO invente dados que não "
    "foram informados (marca, medidas, garantia, conteúdo). Responda apenas com o texto "
    "da descrição, sem títulos nem aspas."
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
    "português do Brasil para ser mais atraente e fácil de encontrar na busca, incluindo "
    "marca, modelo e principais características. Use no MÁXIMO 60 caracteres, sem CAIXA ALTA "
    "excessiva e sem emojis. Responda apenas com o novo título, sem aspas."
)

_SYSTEM_VARIACAO = (
    "Você é um vendedor do Mercado Livre. Reescreva a mensagem a seguir mantendo o mesmo "
    "sentido, em português do Brasil, com um tom cordial e natural, um pouco diferente do "
    "original. Responda apenas com o novo texto, sem aspas."
)

_SYSTEM_ASSISTENTE = (
    "Você é um assistente que ajuda vendedores do Mercado Livre no Brasil. Responda à "
    "pergunta de forma prática e objetiva, em português do Brasil, com dicas acionáveis. "
    "Se não tiver certeza, seja honesto. Responda em até 2 parágrafos curtos."
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
    return _gerar(_SYSTEM, prompt, timeout=timeout)


def gerar_descricao(titulo: str, marca: str = "", timeout: float = 60.0) -> str:
    """Gera a descrição de um anúncio a partir do título (e marca). '' em falha."""
    titulo = (titulo or "").strip()
    if not titulo or not habilitada():
        return ""
    prompt = f"Título do anúncio: {titulo}\n"
    if marca.strip():
        prompt += f"Marca: {marca.strip()}\n"
    prompt += "Descrição sugerida:"
    return _gerar(_SYSTEM_DESCRICAO, prompt, timeout=timeout, num_predict=400)


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
    return novo[:60].strip()


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
