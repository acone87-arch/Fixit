from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    secret_key: str
    access_token_expire_minutes: int = 480
    algorithm: str = "HS256"
    public_app_url: str = "http://localhost:8000"  # базовый URL для ссылок в QR-кодах

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
