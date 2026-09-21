from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://ledger:${POSTGRES_PASSWORD}@localhost:5234/ledger"
    jwt_secret: str = "dev-only-not-a-real-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900
    rate_limit_per_minute: int = 120

settings = Settings()