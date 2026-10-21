"""
Central configuration for the app.

Why this file exists:
Instead of scattering `os.environ.get(...)` calls across the codebase,
we define one Settings object. Every other module imports `settings`
from here. This makes it obvious what config the app depends on,
and makes testing easier (you can override settings in one place).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App identity
    APP_NAME: str = "Vehicle QR Alert System"
    ENV: str = "development"

    # Database
    # Defaults to a local SQLite file so the app runs with zero setup.
    # In production this is overridden via env var to point at Postgres,
    # e.g. postgresql://user:pass@host:5432/dbname
    DATABASE_URL: str = "sqlite:///./vehicle_qr_alert.db"

    # Security
    SECRET_KEY: str = "dev-only-secret-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # QR token
    QR_TOKEN_BYTES: int = 32  # raw entropy of each generated QR token

    # Base URL the app is served from. The QR code encodes a full link
    # built from this (e.g. http://localhost:8000/report/<token>) so
    # that scanning it with a phone camera opens the report page
    # directly, instead of just showing raw text.
    BASE_URL: str = "http://localhost:8000"

    # AI service (keyword/risk scoring on alerts)
    # If no key is present, the AI service degrades gracefully to a
    # rule-based keyword matcher instead of failing the request.
    AI_API_KEY: str | None = None
    AI_ENABLED: bool = False

    # Which vision-AI provider to use for the authenticity check.
    #   "anthropic" -- Claude vision API (paid, needs billing credits)
    #   "gemini"    -- Google Gemini API (has a genuine free tier,
    #                  no credit card required, as of 2026 -- good
    #                  default if you don't want to pay for credits)
    # AI_API_KEY holds whichever provider's key you're using.
    AI_PROVIDER: str = "anthropic"

    # Notification policy -- a deliberate product decision, not a bug:
    #   False (default): EVERY report reaches the owner, even ones
    #     flagged "needs_review" or "likely_prank". They're clearly
    #     labeled so the owner can judge for themselves. This protects
    #     against a real emergency being silently dropped just because
    #     the authenticity check (AI or rule-based) got it wrong.
    #   True: ONLY reports the authenticity check marks "likely_genuine"
    #     are forwarded to the owner. Anything else is suppressed
    #     (never sent), not just hidden -- the owner won't know it
    #     happened at all. This cuts noise from mismatched/prank
    #     photos, but means a genuine emergency that the AI misjudges
    #     (e.g. a blurry photo, an unusual angle) never reaches the
    #     owner. Turn this on only if you've accepted that trade-off.
    NOTIFY_ONLY_ON_VERIFIED: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
