"""Configurações da aplicação, carregadas do arquivo .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Credenciais da aplicação no Mercado Livre (DevCenter)
    meli_client_id: str = ""
    meli_client_secret: str = ""
    # Página-ponte HTTPS (GitHub Pages) que devolve o code para o app local.
    # É a MESMA URL para todos os usuários; basta cadastrá-la no DevCenter.
    meli_redirect_uri: str = (
        "https://tbongiovani-outlook.github.io/MeuMercado/callback.html"
    )

    # Endpoints
    meli_auth_domain: str = "https://auth.mercadolivre.com.br"
    meli_api_base: str = "https://api.mercadolibre.com"

    # Sessão e banco local
    app_secret_key: str = "change-me"
    database_path: str = "meu_mercado.db"

    @property
    def is_configured(self) -> bool:
        return bool(self.meli_client_id and self.meli_client_secret)


settings = Settings()
