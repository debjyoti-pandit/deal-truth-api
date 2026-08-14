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
    # text (default) or json — one JSON object per line for log aggregators.
    log_format: str = "text"
    public_api_base_url: str = "http://localhost:8000"
    # Web app origin used for share links (e.g. http://localhost:5173). Empty -> relative /shared/{token}.
    public_web_base_url: str = ""

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
    # A one-hour recording can take PyAI well over ten minutes to transcribe; the old
    # 600s default turned a long call into PYAI_JOB_TIMEOUT.
    pyai_poll_deadline_seconds: float = 1800.0

    ml_service_base_url: str = "http://localhost:8081"
    ml_service_api_key: str = ""
    ml_generation_enabled: bool = True
    # Per-request item cap when batching to the Worker. Must not exceed the Worker's
    # MAX_BATCH_SIZE (default 32, advertised on its /health/ready). The client chunks to
    # this size, so call length is never bounded by it.
    ml_max_batch_size: int = 32

    # Hosts a Slack incoming-webhook URL may point at. An allowlist, not a hint: a URL whose
    # host is not in here is rejected with `WEBHOOK_URL_INVALID`, as is any non-https URL.
    # The webhook itself is never a setting — it is user data and lives in the database.
    slack_webhook_hosts: str = "hooks.slack.com"

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
    def slack_webhook_host_set(self) -> frozenset[str]:
        return frozenset(h.strip().lower() for h in self.slack_webhook_hosts.split(",") if h.strip())

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
    def resolved_ml_service_base_url(self) -> str:
        """`ML_SERVICE_BASE_URL`, else the local dev Worker. The ngrok fallback is gone:
        the ML service is deployed (https://deal-truth-ml.onrender.com), so a tunnel is no
        longer part of the resolution chain — point the env var wherever the service is."""
        raw = self.ml_service_base_url.strip().rstrip("/")
        return raw if raw else "http://localhost:8081"

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
