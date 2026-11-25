"""Konfiguration via miljövariabler (.env stöds)."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- Microsoft Graph / Entra ID ---
    ms_client_id: str
    ms_tenant_id: str = "consumers"  # "consumers" för privat MS-konto, annars tenant-GUID
    ms_token_cache: str = "/data/token_cache.json"
    graph_poll_minutes: int = 5

    # --- LLM ---
    anthropic_api_key: str
    classify_model: str = "claude-haiku-4-5-20251001"
    analyze_model: str = "claude-sonnet-4-6"  # djupanalys av protokoll m.m.

    # --- Databas ---
    database_url: str = "postgresql+psycopg://mailroom:mailroom@db:5432/mailroom"

    # --- Beteende ---
    shadow_mode: bool = True  # True = klassificera och logga, rör ALDRIG mailen
    max_body_chars: int = 6000
    max_attachment_mb: int = 15

    # --- Notiser ---
    ntfy_url: str | None = None            # t.ex. https://ntfy.sh/ditt-hemliga-topic
    ha_webhook_url: str | None = None      # Home Assistant webhook, t.ex. http://ha:8123/api/webhook/mailroom

    # --- Din profil (används i prompten) ---
    user_role: str = (
        "Ventilationsprojektör/besiktningsman med eget bolag. "
        "Intresserad av: ventilation, OVK, provtryckning/täthetsprovning, "
        "injustering, ÄTA, tidplaner, ekonomi, beslut som påverkar vent-entreprenaden."
    )


settings = Settings()  # type: ignore[call-arg]
