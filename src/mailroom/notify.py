"""Notiser: ntfy och/eller Home Assistant-webhook. Båda är valfria."""
from __future__ import annotations

import logging

import httpx

from mailroom.config import settings

log = logging.getLogger("mailroom.notify")


def notify(*, title: str, message: str) -> None:
    if settings.ntfy_url:
        try:
            httpx.post(
                settings.ntfy_url,
                content=message.encode(),
                headers={"Title": title.encode("ascii", "ignore").decode()},
                timeout=10,
            )
        except Exception as e:
            log.warning("ntfy misslyckades: %s", e)
    if settings.ha_webhook_url:
        try:
            httpx.post(
                settings.ha_webhook_url,
                json={"title": title, "message": message},
                timeout=10,
            )
        except Exception as e:
            log.warning("HA-webhook misslyckades: %s", e)
