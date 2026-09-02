from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "FINEX POS"
    jwt_secret: str = "finup-pos-dev-secret-change-me"
    jwt_alg: str = "HS256"
    jwt_hours: int = 12
    database_url: str = "sqlite:///./finup_pos.db"
    cors_origins: str = "http://localhost:5174,http://127.0.0.1:5174,http://127.0.0.1:8001"
    node_env: str = "development"

    platform_owner_login: str = "platform"
    platform_owner_password: str = "platform123"

    app_url: str = "http://127.0.0.1:8001"
    click_service_id: str = ""
    click_merchant_id: str = ""
    click_secret: str = ""
    payme_merchant_id: str = ""
    payme_key: str = ""
    payme_checkout_url: str = "https://checkout.paycom.uz"

    ai_enabled: bool = True
    ai_provider: str = "openai"
    ai_api_key: str = ""
    ai_base_url: str = "https://api.openai.com/v1"
    ai_model: str = "gpt-4o-mini"
    ai_max_tokens: int = 800
    ai_timeout_sec: float = 25
    ai_max_history: int = 12
    ai_max_message_chars: int = 2000
    ai_rate_limit: int = 30
    ai_rate_window: int = 3600
    ai_temperature: float = 0.3



settings = Settings()
