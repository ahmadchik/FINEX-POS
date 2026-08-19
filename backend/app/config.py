from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "FINEX POS"
    jwt_secret: str = "finup-pos-dev-secret-change-me"
    jwt_alg: str = "HS256"
    jwt_hours: int = 12
    database_url: str = "sqlite:///./finup_pos.db"
    cors_origins: str = "http://localhost:5174,http://127.0.0.1:5174"


settings = Settings()
