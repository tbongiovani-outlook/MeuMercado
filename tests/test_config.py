"""Testes das configurações (pydantic-settings)."""

from app.config import Settings


def test_defaults_nao_configurado():
    s = Settings(_env_file=None)
    assert s.is_configured is False
    assert s.meli_api_base.startswith("https://")
    assert s.database_path


def test_is_configured_quando_credenciais_presentes():
    s = Settings(_env_file=None, meli_client_id="abc", meli_client_secret="xyz")
    assert s.is_configured is True
