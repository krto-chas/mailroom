"""LLM-klassificering av mail + djupanalys av protokollbilagor.

Klassificeraren får projektlistan i prompten och svarar med strikt JSON.
Mänskliga rättningar (corrected=True) plockas in som few-shot-exempel —
systemet blir alltså bättre av att du rättar det.
"""
from __future__ import annotations

import json
from typing import Any

import anthropic

from mailroom.config import settings

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

CATEGORIES = (
    "projektinfo, motesprotokoll, leverantorsfaktura, kundfaktura, "
    "forfragan, admin, privat, brus"
)

SYSTEM = """Du är en mailklassificerare för en svensk ventilationskonsult/besiktningsman.

Användarens roll: {role}

Klassificera mailet. Svara med ENDAST ett JSON-objekt, inga backticks, ingen text runt:
{{
  "project_slug": "<slug ur projektlistan, eller null om inget matchar>",
  "category": "<en av: {categories}>",
  "priority": <1 viktig/brådskande, 2 normal, 3 lågt>,
  "summary": "<1-2 meningar på svenska: vad handlar mailet om, vad förväntas av mottagaren>",
  "flags": [
    {{"text": "<viktig punkt att uppmärksamma>", "why": "<varför relevant för användaren>", "severity": <1|2|3>}}
  ]
}}

Regler:
- Matcha projekt på namn, alias, avsändardomän OCH innehåll. Osäker → null.
- "flags" endast för saker som kräver användarens uppmärksamhet (beslut, deadlines,
  kostnadspåverkan, krav på svar). Vanlig info → tom lista.
- Nyhetsbrev, reklam, automatiska notiser → "brus", priority 3.
- Faktura FRÅN leverantör till användaren → leverantorsfaktura.
  Betalning/påminnelse på användarens egen faktura → kundfaktura."""


def _project_block(projects: list[dict[str, Any]]) -> str:
    lines = ["Aktiva projekt (slug | namn | alias | kända domäner):"]
    for p in projects:
        lines.append(
            f"- {p['slug']} | {p['name']} | {', '.join(p['aliases']) or '-'} | "
            f"{', '.join(p['sender_domains']) or '-'}"
        )
    return "\n".join(lines) if projects else "Inga projekt registrerade ännu."


def _fewshot_block(corrections: list[dict[str, Any]]) -> str:
    if not corrections:
        return ""
    lines = ["Tidigare rättade exempel (facit från användaren — följ dessa mönster):"]
    for c in corrections[:10]:
        lines.append(
            f"- Avsändare: {c['sender']} | Ämne: {c['subject']}\n"
            f"  Rätt: projekt={c['project_slug']}, kategori={c['category']}"
            + (f" ({c['note']})" if c.get("note") else "")
        )
    return "\n".join(lines)


def _parse_json(text: str) -> dict[str, Any]:
    clean = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return dict(json.loads(clean))


def classify_email(
    *,
    sender: str,
    subject: str,
    body: str,
    attachment_names: list[str],
    projects: list[dict[str, Any]],
    corrections: list[dict[str, Any]],
) -> dict[str, Any]:
    user_msg = (
        f"{_project_block(projects)}\n\n{_fewshot_block(corrections)}\n\n"
        f"--- MAIL ---\n"
        f"Avsändare: {sender}\nÄmne: {subject}\n"
        f"Bilagor: {', '.join(attachment_names) or 'inga'}\n\n"
        f"{body[: settings.max_body_chars]}"
    )
    resp = _client.messages.create(
        model=settings.classify_model,
        max_tokens=1024,
        system=SYSTEM.format(role=settings.user_role, categories=CATEGORIES),
        messages=[{"role": "user", "content": user_msg}],
    )
    return _parse_json(resp.content[0].text)


ANALYZE_SYSTEM = """Du analyserar ett dokument (t.ex. byggmötesprotokoll) åt en svensk
ventilationskonsult/besiktningsman.

Användarens roll: {role}

Extrahera ENDAST punkter som är relevanta för användaren. Svara med ENDAST JSON:
{{
  "findings": [
    {{"locator": "<sida/paragraf om identifierbart, annars tom sträng>",
      "text": "<punkten, kort och sakligt på svenska>",
      "why": "<varför den rör användaren>",
      "severity": <1 kräver agerande, 2 bör noteras, 3 info>}}
  ]
}}
Inga relevanta punkter → tom lista. Hitta ALDRIG på innehåll som inte står i dokumentet."""


def analyze_document(*, filename: str, text: str) -> list[dict[str, Any]]:
    resp = _client.messages.create(
        model=settings.analyze_model,
        max_tokens=2048,
        system=ANALYZE_SYSTEM.format(role=settings.user_role),
        messages=[
            {
                "role": "user",
                "content": f"Dokument: {filename}\n\n{text[:60000]}",
            }
        ],
    )
    return list(_parse_json(resp.content[0].text).get("findings", []))
