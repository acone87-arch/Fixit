from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from decimal import Decimal


class Settings(BaseSettings):
    database_url: str
    secret_key: str
    access_token_expire_minutes: int = 480
    algorithm: str = "HS256"
    public_app_url: str = "http://localhost:8000"  # базовый URL для ссылок в QR-кодах
    vapid_public_key: str | None = None
    vapid_private_key: str | None = None
    vapid_subject: str | None = None
    password_reset_expire_minutes: int = 30
    password_reset_debug: bool = False
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True
    # Explicit opt-in: UUIDs, not organization names/slugs supplied by a browser.
    ai_enabled: bool = False
    ai_organization_ids: str = ""
    # Optional additional restriction within service tenants. Empty = all their clients.
    ai_client_ids: str = ""
    ai_repair_enabled: bool = False
    ai_brief_enabled: bool = False
    yandex_gpt_api_key: str | None = None
    yandex_gpt_folder_id: str | None = None
    ai_model: str = "yandexgpt-5.1"
    ai_timeout_seconds: int = Field(default=30, ge=1, le=60)
    ai_monthly_limit_rub: Decimal = Field(default=Decimal("300"), ge=0, le=300)
    ai_daily_limit_rub: Decimal = Field(default=Decimal("10"), ge=0, le=10)
    ai_input_rub_per_1000: Decimal = Field(default=Decimal("0.8"), gt=0)
    ai_output_rub_per_1000: Decimal = Field(default=Decimal("0.8"), gt=0)
    # Conservatively carry forward the existing diagnostic estimate + unknown
    # reserve; this is not an observed cloud bill. Override only after reconciliation.
    ai_prior_accounted_rub: Decimal = Field(default=Decimal("6.3992"), ge=0)
    ai_prior_accounted_date: str = "2026-10-19"
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
