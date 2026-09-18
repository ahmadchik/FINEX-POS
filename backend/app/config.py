from pydantic_settings import BaseSettings, SettingsConfigDict

# Development placeholders only. Production must override via environment.
JWT_DEV_PLACEHOLDER = "finup-pos-dev-secret-change-me"
PLATFORM_DEV_PASSWORD_PLACEHOLDER = "platform123"

_INSECURE_JWT_NEEDLES = ("change-me", "changeme", "dev-secret", "placeholder", "your-secret")
_INSECURE_PLATFORM_PASSWORDS = frozenset({"password", "admin", "123456", "qwerty"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "FINEX POS"
    jwt_secret: str = JWT_DEV_PLACEHOLDER
    jwt_alg: str = "HS256"
    jwt_hours: int = 12
    database_url: str = "sqlite:///./finup_pos.db"
    cors_origins: str = "http://localhost:5174,http://127.0.0.1:5174,http://127.0.0.1:8001"
    node_env: str = "development"

    platform_owner_login: str = "platform"
    platform_owner_password: str = PLATFORM_DEV_PASSWORD_PLACEHOLDER

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



DEV_CORS_ORIGINS = (
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://127.0.0.1:8001",
    "http://localhost:8001",
)


def cors_origin_list(cfg: "Settings | None" = None) -> list[str]:
    """Explicit origins only. Never returns '*' (unsafe with credentials)."""
    cfg = cfg or settings
    raw = [o.strip() for o in (cfg.cors_origins or "").split(",") if o.strip()]
    if "*" in raw:
        if is_production_env(cfg.node_env):
            raise RuntimeError("Production CORS_ORIGINS cannot include *.")
        raw = [o for o in raw if o != "*"]
    if not raw:
        if is_production_env(cfg.node_env):
            # Same-origin SPA: no cross-origin allow-list (do not fall back to *).
            return []
        return list(DEV_CORS_ORIGINS)
    return raw


def is_production_env(node_env: str) -> bool:
    return (node_env or "").strip().lower() in {"production", "prod"}


def _jwt_is_insecure(secret: str) -> bool:
    s = (secret or "").strip()
    if not s or s == JWT_DEV_PLACEHOLDER:
        return True
    low = s.lower()
    return any(n in low for n in _INSECURE_JWT_NEEDLES)


def _platform_password_is_insecure(password: str) -> bool:
    s = (password or "").strip()
    if not s or s == PLATFORM_DEV_PASSWORD_PLACEHOLDER:
        return True
    return s.lower() in _INSECURE_PLATFORM_PASSWORDS


def validate_runtime_secrets(cfg: Settings | None = None) -> None:
    """Fail-fast in production if JWT/platform secrets are missing or known-insecure."""
    cfg = cfg or settings
    if not is_production_env(cfg.node_env):
        return
    secret = (cfg.jwt_secret or "").strip()
    if _jwt_is_insecure(secret) or len(secret) < 32:
        raise RuntimeError(
            "Production JWT_SECRET is missing, too short, or insecure. "
            "Set a unique JWT_SECRET (min 32 characters)."
        )
    if _platform_password_is_insecure(cfg.platform_owner_password or ""):
        raise RuntimeError(
            "Production PLATFORM_OWNER_PASSWORD is missing or insecure. "
            "Set PLATFORM_OWNER_PASSWORD."
        )
    if not (cfg.platform_owner_login or "").strip():
        raise RuntimeError("Production PLATFORM_OWNER_LOGIN is missing.")
    if "*" in [o.strip() for o in (cfg.cors_origins or "").split(",") if o.strip()]:
        raise RuntimeError("Production CORS_ORIGINS cannot include *.")


settings = Settings()
