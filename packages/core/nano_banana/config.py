"""Конфигурация приложения."""
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_WEAK_SECRET_KEYS = {
    "",
    "secret",
    "changeme",
    "change-me",
    "your-secret-key-change-in-production",
    "nano_banana_secret",
    "change-me-jwt-secret-min-32-characters-long",
}
_WEAK_PASSWORDS = {
    "nano_banana_pass",
    "password",
    "postgres",
    "minioadmin123",
    "minioadmin",
    "change-me",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin123"
    MINIO_SECURE: bool = False
    MINIO_BUCKET: str = "nano-banana-images"
    MINIO_PUBLIC_URL: str = "http://localhost:9000"
    MINIO_PRESIGN_EXPIRES_SECONDS: int = 900

    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "nano_banana"
    POSTGRES_USER: str = "nano_banana_user"
    POSTGRES_PASSWORD: str = "nano_banana_pass"

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    SECRET_KEY: str
    DATA_ENCRYPTION_KEY: str = ""
    REDIS_URL: str = "redis://localhost:6379/0"
    # Beget: false + presigned URLs. Local MinIO can set true for convenience.
    S3_PUBLIC_READ: bool = False
    WORKER_ID: str = ""
    JOB_LOCK_TTL_SECONDS: int = 180
    STUCK_GENERATION_MINUTES: int = 20
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    PWD_SCHEMES: str = "bcrypt"
    SECURITY_ALLOW_PUBLIC_REGISTER: bool = False
    ADMIN_BOOTSTRAP_SECRET: str = ""

    BANANALAB_API_BASE_URL: str = "https://api.moonez.ai/api"
    REPLICATE_API_TOKEN: str = ""
    BANANALAB_BASE_URL: str = "https://api.moonez.ai/api"

    @field_validator("BANANALAB_BASE_URL", "BANANALAB_API_BASE_URL", mode="before")
    @classmethod
    def _normalize_moonez_domain(cls, value):
        """BananaHub продан → Moonez; старые хосты принудительно переписываем."""
        if not isinstance(value, str):
            return value
        rewritten = value
        for old in (
            "https://bananahub.io/api",
            "https://www.bananahub.io/api",
            "https://bananahub.app/api",
            "https://www.bananahub.app/api",
            "https://api.bananalab.pw",
        ):
            if rewritten.startswith(old):
                rewritten = "https://api.moonez.ai/api" + rewritten[len(old) :]
                break
        rewritten = rewritten.replace("bananahub.io", "api.moonez.ai")
        rewritten = rewritten.replace("bananahub.app", "api.moonez.ai")
        return rewritten

    BANANALAB_UPSTREAM_NO_IMAGE_MAX_RETRIES: int = 5
    BANANALAB_UPSTREAM_NO_IMAGE_RETRY_BASE_DELAY_SECONDS: float = 3.0

    OPENROUTER_HTTP_REFERER: str = ""
    OPENROUTER_X_TITLE: str = "Nano Banana Pro"
    OPENROUTER_PROMPT_REWRITE_MODEL: str = "openai/gpt-4o-mini"
    OPENROUTER_PROMPT_REWRITE_MODEL_FALLBACKS: str = (
        "google/gemini-2.0-flash-001,meta-llama/llama-3.3-70b-instruct"
    )
    MAX_POLICY_GPT_RETRIES: int = 2

    MAX_WORKERS: int = 1
    MAX_CONCURRENT_GENERATIONS: int = 1

    CORS_ORIGINS: str = "http://localhost:8000"
    API_URL: str = "http://localhost:8000"

    SECURITY_STRICT_CSP: bool = True
    SECURITY_ENABLE_HSTS: bool = True
    SECURITY_LOGIN_MAX_ATTEMPTS: int = 10
    SECURITY_LOGIN_WINDOW_SECONDS: int = 300
    SECURITY_ADMIN_READ_MAX_REQUESTS: int = 120
    SECURITY_ADMIN_READ_WINDOW_SECONDS: int = 60
    SECURITY_CSP_ALLOW_INLINE_SCRIPTS: bool = False
    SECURITY_CSP_ALLOW_MINIO_CONSOLE_FRAME: bool = False
    SECURITY_DISABLE_OPENAPI: bool = True
    SECURITY_REGISTER_MAX_ATTEMPTS: int = 10
    SECURITY_REGISTER_WINDOW_SECONDS: int = 3600
    SECURITY_ALLOWED_REF_URL_HOSTS: str = ""
    SECURITY_ALLOWED_OUTBOUND_IMAGE_HOSTS: str = ""

    @model_validator(mode="after")
    def _reject_weak_secrets(self):
        sk = (self.SECRET_KEY or "").strip()
        if len(sk) < 32 or sk.lower() in _WEAK_SECRET_KEYS:
            raise ValueError(
                "SECRET_KEY must be a strong value (>=32 chars). Do not use example defaults."
            )
        if (self.POSTGRES_PASSWORD or "").strip().lower() in _WEAK_PASSWORDS:
            raise ValueError("POSTGRES_PASSWORD is weak — set a strong password in .env")
        if (self.MINIO_SECRET_KEY or "").strip().lower() in _WEAK_PASSWORDS:
            raise ValueError("MINIO_SECRET_KEY is weak — set a strong password in .env")
        api_lower = (self.API_URL or "").lower()
        if self.S3_PUBLIC_READ and api_lower.startswith("https://") and "localhost" not in api_lower:
            raise ValueError("S3_PUBLIC_READ=true запрещён в production (API_URL=https)")
        if api_lower.startswith("https://") and "localhost" not in api_lower:
            dek = (self.DATA_ENCRYPTION_KEY or "").strip()
            if len(dek) < 32 or dek == (self.SECRET_KEY or "").strip():
                raise ValueError(
                    "DATA_ENCRYPTION_KEY must be set in production (>=32 chars, distinct from SECRET_KEY)"
                )
        return self


settings = Settings()
