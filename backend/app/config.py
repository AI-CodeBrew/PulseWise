"""
App settings, read from environment variables (backend/.env).

Since Phase 4, a website's PostHog connection details are NOT in .env any more:
they live in the `websites` table (API key encrypted). `WebsiteConfig` below is the
plain object the rest of the app receives for "the website this request is about".
See app/deps.py -> get_website_config() for how it is loaded and access-checked.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env no matter which folder the app was started from.
# Real environment variables win over .env (load_dotenv does not override them).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _list(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    # --- Database (Supabase Postgres) ---
    database_url: str

    # --- Security ---
    jwt_secret: str  # signs login cookies
    encryption_keys: list[str]  # Fernet key(s) for stored PostHog API keys; first one encrypts
    session_days: int  # how long a login lasts
    cookie_secure: bool  # cookies only over HTTPS (must be true in production)

    # --- PostHog hosts we may send API keys to (protects against typos and misuse) ---
    posthog_allowed_hosts: list[str]

    # --- Frontend ---
    brand_name: str  # the product name shown on invoices and in emails
    frontend_url: str  # used in password-reset links
    cors_origins: list[str]  # which browser origins may call this API

    # --- Background jobs ---
    scheduler_enabled: bool  # run the hourly/daily jobs inside this process

    # --- Caching ---
    cache_ttl_seconds: int
    live_cache_ttl_seconds: int

    # --- Email (password reset). Without SMTP_HOST, emails are printed to the console. ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = field(default="", repr=False)
    smtp_from: str = ""
    smtp_starttls: bool = True

    # --- AI-written report summaries (optional): empty = rule-based summaries instead ---
    anthropic_api_key: str = field(default="", repr=False)

    # --- WhatsApp weekly reports (optional): empty = no WhatsApp messages ---
    whatsapp_access_token: str = field(default="", repr=False)
    whatsapp_phone_number_id: str = ""


def load_settings() -> Settings:
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000").strip().rstrip("/")
    return Settings(
        database_url=os.getenv("DATABASE_URL", "").strip(),
        jwt_secret=os.getenv("JWT_SECRET", "").strip(),
        encryption_keys=_list("ENCRYPTION_KEY", ""),
        session_days=int(os.getenv("SESSION_DAYS", "7")),
        # Default: secure cookies whenever the site itself runs on https.
        cookie_secure=_bool("COOKIE_SECURE", frontend_url.startswith("https://")),
        posthog_allowed_hosts=["https://us.posthog.com", "https://eu.posthog.com"]
        + [h.rstrip("/") for h in _list("POSTHOG_ALLOWED_HOSTS", "")],  # add self-hosted addresses here
        brand_name=os.getenv("BRAND_NAME", "").strip() or "PulseWise",
        frontend_url=frontend_url,
        cors_origins=_list("CORS_ORIGINS", frontend_url),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        whatsapp_access_token=os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip(),
        whatsapp_phone_number_id=os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip(),
        scheduler_enabled=_bool("SCHEDULER_ENABLED", True),
        cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS", "300")),  # 5 minutes
        live_cache_ttl_seconds=int(os.getenv("LIVE_CACHE_TTL_SECONDS", "10")),
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_user=os.getenv("SMTP_USER", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", "").strip(),
        smtp_starttls=_bool("SMTP_STARTTLS", True),
    )


settings = load_settings()


def missing_settings() -> list[str]:
    """Names of required settings that are not set (checked when the app starts)."""
    missing = []
    if not settings.database_url:
        missing.append("DATABASE_URL")
    if not settings.jwt_secret:
        missing.append("JWT_SECRET")
    if not settings.encryption_keys:
        missing.append("ENCRYPTION_KEY")
    return missing


@dataclass(frozen=True)
class WebsiteConfig:
    """Everything needed to read ONE website's data from PostHog.

    Built per request from the `websites` table, AFTER checking that the logged-in
    user may see this website (app/deps.py). Services only ever receive this object.
    """

    website_id: str  # our id (UUID as text), also used in cache keys
    name: str
    posthog_host: str  # https://us.posthog.com or https://eu.posthog.com
    project_id: int
    # repr=False -> the decrypted key never appears in logs, errors or tracebacks.
    api_key: str = field(repr=False)
    client_id: str = ""  # the client that owns this website (to check the client's plan)
    role: str = "owner"  # what the person asking is for this website: "admin", "owner" or "viewer"
