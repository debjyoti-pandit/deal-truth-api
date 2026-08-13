"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import AudioInputMode, AuthMode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "deal-truth-api"
    app_env: str = "development"
    log_level: str = "INFO"
    public_api_base_url: str = "http://localhost:8000"

    ngrok_enabled: bool = True
    ngrok_api_url: str = "http://127.0.0.1:4040"
    ngrok_wait_seconds: float = 30.0
    ngrok_domain: str = ""

    auth_mode: AuthMode = AuthMode.NONE
    api_keys: str = ""
    cors_origins: str = "http://localhost:5173"

    database_url: str = "postgresql+asyncpg://deal_truth:deal_truth@localhost:5432/deal_truth"
    database_sync_url: str = "postgresql+psycopg://deal_truth:deal_truth@localhost:5432/deal_truth"

    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    s3_endpoint_url: str = "http://localhost:8333"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    s3_bucket_audio: str = "deal-truth-audio"
    s3_bucket_results: str = "deal-truth-results"
    s3_bucket_samples: str = "deal-truth-samples"
    s3_use_ssl: bool = False
    s3_addressing_style: str = "path"

    max_audio_bytes: int = 524_288_000
    allowed_audio_mime_types: str = (
        "audio/mpeg,audio/wav,audio/x-wav,audio/wave,audio/mp4,audio/ogg,audio/webm,audio/flac,audio/x-m4a,video/mp4"
    )
    allowed_audio_extensions: str = ".mp3,.wav,.m4a,.ogg,.webm,.flac,.mp4"

    pyai_api_key: str = ""
    pyai_base_url: str = "https://api.pyai.com/v1"
    pyai_webhook_secret: str = ""
    pyai_recap_enabled: bool = True
    pyai_trace_enabled: bool = False
    pyai_recap_pack_id: str = "sales_outbound"
    pyai_audio_input_mode: AudioInputMode = AudioInputMode.AUDIO_URL
    pyai_poll_interval_seconds: float = 5.0
    pyai_poll_deadline_seconds: float = 600.0

    ml_service_base_url: str = "http://localhost:8081"
    ml_service_api_key: str = ""
    ml_generation_enabled: bool = True

    signed_url_ttl_seconds: int = 900
    signed_url_secret: str = ""

    share_token_ttl_seconds: int = 604_800

    stereo_default_channel_seller: int = 0
    confidence_threshold: float = 0.5

    source_fetch_timeout_seconds: float = 30.0
    source_fetch_max_redirects: int = 3

    celery_max_retries: int = 5
    celery_retry_backoff: int = 2
    celery_retry_backoff_max: int = 60

    @field_validator("stereo_default_channel_seller")
    @classmethod
    def _channel(cls, value: int) -> int:
        if value not in (0, 1):
            raise ValueError("STEREO_DEFAULT_CHANNEL_SELLER must be 0 or 1")
        return value

    @property
    def api_key_set(self) -> frozenset[str]:
        return frozenset(k.strip() for k in self.api_keys.split(",") if k.strip())

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        domain = self.ngrok_domain.strip().removeprefix("https://").removeprefix("http://")
        host = domain.split("/")[0].lower() if domain else ""
        if host and host not in {"localhost", "127.0.0.1"}:
            extra = f"https://{host}"
            if extra not in origins:
                origins.append(extra)
        return origins

    @property
    def allowed_mime_set(self) -> frozenset[str]:
        return frozenset(m.strip().lower() for m in self.allowed_audio_mime_types.split(",") if m.strip())

    @property
    def allowed_ext_set(self) -> frozenset[str]:
        return frozenset(
            e.strip().lower() if e.strip().startswith(".") else f".{e.strip().lower()}"
            for e in self.allowed_audio_extensions.split(",")
            if e.strip()
        )

    @property
    def hmac_secret(self) -> bytes:
        if not self.signed_url_secret:
            raise RuntimeError("SIGNED_URL_SECRET must be set")
        return self.signed_url_secret.encode("utf-8")

    @property
    def webhook_secret_bytes(self) -> bytes:
        return self.pyai_webhook_secret.encode("utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
