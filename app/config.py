from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    secret_key: str
    access_token_expire_minutes: int = 480
    algorithm: str = "HS256"
    public_app_url: str = "http://localhost:8000"  # базовый URL для ссылок в QR-кодах
    vapid_public_key: str | None = None
    vapid_private_key: str | None = None
    vapid_subject: str | None = None
    # Comma-separated values keep the production .env readable and avoid JSON
    # syntax in shell-managed deployment configuration.
    allowed_origins: str = "http://localhost:8000,http://127.0.0.1:8000"
    allowed_hosts: str = "localhost,127.0.0.1"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @staticmethod
    def _split_csv(value: str) -> list[str]:
        return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return self._split_csv(self.allowed_origins)

    @property
    def trusted_hosts(self) -> list[str]:
        return self._split_csv(self.allowed_hosts)


settings = Settings()
