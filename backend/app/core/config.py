"""Single source of truth for runtime configuration.

Every module that needs a setting imports `get_settings()` from here — nothing reads
`os.environ` directly anywhere else in the codebase. That keeps `.env.example` authoritative
and makes it possible to override settings in tests via `Settings(**overrides)`.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"  # development | test | production
    log_level: str = "INFO"
    # Comma-separated origins allowed to call the API cross-origin — needed once the frontend
    # is deployed as a separate Render static site (a different origin than the backend). "*"
    # is fine for a single-tenant demo with no cookie-based auth (there is none here); set to
    # the deployed frontend's exact origin for anything beyond a demo.
    cors_allowed_origins: str = "*"

    database_url: str = "postgresql+asyncpg://recoveryos:recoveryos@localhost:5432/recoveryos"

    @field_validator("database_url")
    @classmethod
    def _normalize_asyncpg_scheme(cls, value: str) -> str:
        """Render's `fromDatabase: {property: connectionString}` (used in render.yaml) — and
        most managed-Postgres providers — hand out a plain `postgresql://`/`postgres://` URL.
        SQLAlchemy's async engine needs the `+asyncpg` driver suffix explicitly; rewriting it
        here means every other module can just trust `settings.database_url` is always
        immediately usable, instead of every deployment target needing to know this detail.
        """
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value[len("postgres://") :]
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value[len("postgresql://") :]
        return value

    # Razorpay — Test Mode credentials only. See docs/razorpay-integration.md.
    # key_id/key_secret empty -> gateway_factory.py falls back to the simulator adapters.
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    # NOT empty by default, unlike the two above: the simulator (simulator/generators/) signs
    # every event it generates with this exact secret and sends it through the real
    # POST /api/webhooks/razorpay signature-verification code path — the same path real
    # Razorpay webhooks go through — so the demo works out of the box with zero
    # configuration, without ever bypassing signature verification to do it. This is a local
    # development default, NOT a real Razorpay-issued secret; replace it with the value from
    # your Razorpay Dashboard's webhook settings for real test-mode integration.
    razorpay_webhook_secret: str = "recoveryos-local-dev-webhook-secret"

    # LLM — provider abstracted behind app/agents/ai_diagnostician.py.
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-5"
    llm_api_key: str = ""

    # Recovery policy thresholds — see docs/decisions.md ADR-006 for how these were chosen.
    # min_confidence=0.15 is calibrated against the trained model's actual output range
    # (~5-80%, mean ~24% — this is a recovery-probability model on an inherently low-base-rate
    # problem, not a coin flip; a naive 0.5 threshold would reject nearly everything).
    min_recovery_probability: float = 0.15
    min_expected_value: float = 0.05
    min_confidence: float = 0.15
    max_retries: int = 3
    recovery_window_hours: int = 168

    # Revenue Signal Engine — see app/services/revenue_signal_service.py's revenue_at_risk().
    min_amount_at_risk_paise: int = 100  # ₹1 — excludes trivial/test amounts, not a real floor

    # Simple placeholder cost model — see docs/decisions.md ADR-006 and optimizer_service.py.
    default_intervention_cost_paise: int = 20
    hinglish_voice_intervention_cost_paise: int = 500
    hinglish_voice_risk_cost_paise: int = 100
    notification_risk_cost_paise: int = 10

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_allowed_origins.strip() == "*":
            return ["*"]
        origins = [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]
        # Render's `fromService: {property: host}` env var interpolation (used in
        # render.yaml) yields a bare hostname, not a full origin — the browser's Origin
        # header always includes the scheme, so a bare host would never match.
        return [o if "://" in o else f"https://{o}" for o in origins]


@lru_cache
def get_settings() -> Settings:
    return Settings()
