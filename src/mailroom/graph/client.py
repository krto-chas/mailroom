"""Tunn Microsoft Graph-klient: delta-läsning av inkorgen, bilagor, åtgärder.

Delta queries = vi frågar "vad är nytt sedan sist?" och Graph håller reda på
tillståndet via en deltaLink som vi persisterar i databasen. Dumsäkert och
robust mot omstarter — inga webhooks behövs i v0.1.
"""
from __future__ import annotations

import base64
from typing import Any

import httpx

from mailroom.config import settings
from mailroom.graph.auth import acquire_token

GRAPH = "https://graph.microsoft.com/v1.0"

SELECT = (
    "id,subject,from,receivedDateTime,bodyPreview,body,hasAttachments,"
    "conversationId,internetMessageId,categories,parentFolderId"
)


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"Authorization": f"Bearer {acquire_token()}"},
        timeout=60,
    )


def fetch_delta(delta_link: str | None) -> tuple[list[dict[str, Any]], str]:
    """Hämta nya/ändrade mail i inkorgen. Returnerar (messages, ny deltaLink)."""
    url = delta_link or (
        f"{GRAPH}/me/mailFolders/inbox/messages/delta?$select={SELECT}&$top=50"
    )
    messages: list[dict[str, Any]] = []
    with _client() as c:
        while True:
            r = c.get(url)
            if r.status_code == 410:  # deltaLink utgången → börja om från scratch
                return fetch_delta(None)
            r.raise_for_status()
            data = r.json()
            messages.extend(data.get("value", []))
            if "@odata.nextLink" in data:
                url = data["@odata.nextLink"]
                continue
            return messages, data["@odata.deltaLink"]


def fetch_attachments(message_id: str) -> list[dict[str, Any]]:
    """Lista bilagor med metadata + innehåll (base64) för fileAttachment."""
    max_bytes = settings.max_attachment_mb * 1024 * 1024
    out: list[dict[str, Any]] = []
    with _client() as c:
        r = c.get(f"{GRAPH}/me/messages/{message_id}/attachments")
        r.raise_for_status()
        for a in r.json().get("value", []):
            if a.get("@odata.type") != "#microsoft.graph.fileAttachment":
                continue
            if a.get("size", 0) > max_bytes:
                out.append({"name": a["name"], "size": a["size"], "skipped": "too_large"})
                continue
            out.append(
                {
                    "name": a["name"],
                    "content_type": a.get("contentType"),
                    "size": a.get("size", 0),
                    "content": base64.b64decode(a["contentBytes"]),
                }
            )
    return out


# --- Åtgärder tillbaka mot Outlook (körs ALDRIG i shadow mode) ---

def set_categories(message_id: str, categories: list[str]) -> None:
    with _client() as c:
        r = c.patch(f"{GRAPH}/me/messages/{message_id}", json={"categories": categories})
        r.raise_for_status()


def ensure_folder(display_name: str, parent: str = "inbox") -> str:
    """Hämta eller skapa undermapp till inkorgen. Returnerar folder-id."""
    with _client() as c:
        r = c.get(
            f"{GRAPH}/me/mailFolders/{parent}/childFolders",
            params={"$filter": f"displayName eq '{display_name}'"},
        )
        r.raise_for_status()
        hits = r.json().get("value", [])
        if hits:
            return str(hits[0]["id"])
        r = c.post(
            f"{GRAPH}/me/mailFolders/{parent}/childFolders",
            json={"displayName": display_name},
        )
        r.raise_for_status()
        return str(r.json()["id"])


def move_message(message_id: str, folder_id: str) -> None:
    with _client() as c:
        r = c.post(
            f"{GRAPH}/me/messages/{message_id}/move",
            json={"destinationId": folder_id},
        )
        r.raise_for_status()
