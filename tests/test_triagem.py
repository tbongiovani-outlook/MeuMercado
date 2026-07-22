"""Testes da priorização de perguntas por urgência (heurística de triagem)."""

from datetime import UTC, datetime, timedelta

from app import main


def _pergunta(text, horas=0):
    criado = (datetime.now(UTC) - timedelta(hours=horas)).isoformat()
    return {"id": 1, "text": text, "date_created": criado}


def test_urgencia_alta_por_palavra_chave():
    u = main._classificar_urgencia(_pergunta("O produto veio com defeito, quero reembolso"))
    assert u["nivel"] == "alta"


def test_urgencia_alta_por_espera_longa_com_compra():
    u = main._classificar_urgencia(_pergunta("Quando envia? tem em estoque?", horas=48))
    assert u["nivel"] == "alta"


def test_urgencia_media_por_intencao_de_compra():
    u = main._classificar_urgencia(_pergunta("Vocês fazem entrega para o Rio?"))
    assert u["nivel"] == "média"


def test_urgencia_baixa_pergunta_neutra_recente():
    u = main._classificar_urgencia(_pergunta("Obrigado pela atenção", horas=1))
    assert u["nivel"] == "baixa"


def test_urgencia_data_invalida_nao_quebra():
    u = main._classificar_urgencia({"text": "oi", "date_created": "sem-data"})
    assert u["nivel"] == "baixa"
    assert u["horas"] == 0


def test_priorizar_ordena_urgentes_primeiro():
    perguntas = [
        _pergunta("Obrigado", horas=1),
        _pergunta("Está com defeito, quero cancelar", horas=2),
        _pergunta("Tem disponível?", horas=1),
    ]
    ordenadas = main._priorizar_perguntas(perguntas)
    niveis = [p["urgencia"]["nivel"] for p in ordenadas]
    assert niveis[0] == "alta"
    assert niveis[-1] == "baixa"
