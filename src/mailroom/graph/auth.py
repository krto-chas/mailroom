"""MSAL-autentisering med device code flow + beständig token-cache.

Första körningen: `python -m mailroom.graph.auth` — följ instruktionen
(gå till microsoft.com/devicelogin, ange koden). Därefter förnyas token
automatiskt via refresh token i cachen, så tjänsten kör obevakat.
"""
from __future__ import annotations

import atexit
import os
import sys

import msal

from mailroom.config import settings

SCOPES = ["Mail.Read", "Mail.ReadWrite"]  # ReadWrite krävs för kategorier/flytt (utanför shadow mode)


def _cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if os.path.exists(settings.ms_token_cache):
        with open(settings.ms_token_cache) as f:
            cache.deserialize(f.read())

    def _persist() -> None:
        if cache.has_state_changed:
            os.makedirs(os.path.dirname(settings.ms_token_cache), exist_ok=True)
            with open(settings.ms_token_cache, "w") as f:
                f.write(cache.serialize())
            os.chmod(settings.ms_token_cache, 0o600)

    atexit.register(_persist)
    return cache


def _app() -> msal.PublicClientApplication:
    return msal.PublicClientApplication(
        settings.ms_client_id,
        authority=f"https://login.microsoftonline.com/{settings.ms_tenant_id}",
        token_cache=_cache(),
    )


def acquire_token() -> str:
    """Hämta access token tyst (refresh vid behov). Kastar RuntimeError om
    interaktiv inloggning krävs — kör då device code-flödet nedan."""
    app = _app()
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            return str(result["access_token"])
    raise RuntimeError(
        "Ingen giltig token i cachen. Kör: python -m mailroom.graph.auth"
    )


def device_code_login() -> None:
    app = _app()
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"Kunde inte starta device flow: {flow}")
    print(flow["message"], flush=True)  # "Gå till ... och ange koden ..."
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(f"Inloggning misslyckades: {result.get('error_description')}")
    print("Inloggad. Token-cache sparad:", settings.ms_token_cache)


if __name__ == "__main__":
    try:
        device_code_login()
    except RuntimeError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
