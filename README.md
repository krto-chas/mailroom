# mailroom v0.1

Mail-intake för projektstyrd inkorg: läser inkorgen via Microsoft Graph
(delta queries), klassificerar varje mail per projekt/kategori med LLM,
djupanalyserar PDF-bilagor (t.ex. byggmötesprotokoll) och flaggar punkter
som rör dig. Kör i **shadow mode** som default — inget mail rörs förrän
du slår av det.

## 1. Entra ID-appregistrering (engångsjobb)

1. https://entra.microsoft.com → App registrations → New registration
2. Namn: `mailroom`. Supported account types:
   - Privat outlook.com-konto → "Personal Microsoft accounts only"
   - Microsoft 365-konto (eget bolag) → "Accounts in this organizational directory only"
3. Redirect URI: lämna tom.
4. Under **Authentication**: aktivera *Allow public client flows* = Yes
   (krävs för device code flow).
5. Under **API permissions**: lägg till Microsoft Graph → Delegated →
   `Mail.Read` och `Mail.ReadWrite`. (ReadWrite används först när shadow
   mode stängs av.)
6. Kopiera **Application (client) ID** → `MS_CLIENT_ID` i `.env`.
   Privat konto: `MS_TENANT_ID=consumers`. M365: tenant-GUID:t.

## 2. Starta

```bash
cp .env.example .env       # fyll i client id + Anthropic-nyckel
docker compose up -d db
docker compose build

# Engångsinloggning (device code) — token-cachen hamnar i appdata-volymen:
docker compose run --rm worker python -m mailroom.graph.auth

docker compose up -d
```

API:t: `http://127.0.0.1:8080/docs` (bind:at till localhost — nå via
SSH-tunnel eller WireGuard, exponera inte publikt).

## 3. Registrera projekt

```bash
curl -s -X POST http://127.0.0.1:8080/projects \
  -H 'content-type: application/json' \
  -d '{"slug":"berghallen","name":"Brf Berghällen, Vaxholm",
       "aliases":["Norrberget etapp 2"],"sender_domains":["besqab.se"]}'
```

## 4. Skuggläge → autopilot

Första veckorna: låt worker köra, granska `/emails` och rätta fel:

```bash
curl -s -X POST http://127.0.0.1:8080/emails/17/correct \
  -H 'content-type: application/json' \
  -d '{"project_slug":"berghallen","category":"motesprotokoll",
       "note":"UE-möten hör till Berghällen"}'
```

Rättningarna matas automatiskt in som few-shot-exempel i prompten.
När träffsäkerheten känns bra: `SHADOW_MODE=false` i `.env` och starta om —
då sätts Outlook-kategorier (`MR/<kategori>`, `MR/<projekt>`) på nya mail.

## 5. Notiser

`NTFY_URL` (t.ex. `https://ntfy.sh/<hemligt-topic>`) och/eller
`HA_WEBHOOK_URL`. Notis skickas vid priority 1-mail och severity 1-fynd.
I Home Assistant: skapa en webhook-trigger `mailroom` och gör vad du vill
med `{{ trigger.json.title }}` / `{{ trigger.json.message }}`.

## Arkitektur i korthet

```
worker (var 5:e min)
  └─ Graph delta → nya mail
       └─ Haiku: klassificering {projekt, kategori, prioritet, summary, flags}
       └─ PDF-bilagor (protokoll m.m.) → Sonnet: findings med locator/why/severity
       └─ Postgres: emails / attachments / findings / projects
       └─ shadow_mode? logga : sätt Outlook-kategorier
       └─ viktigt? → ntfy / Home Assistant
api (FastAPI)
  └─ /projects /emails /findings + /correct (few-shot-underlag)
```

## Kända avgränsningar v0.1

- Endast PDF-bilagor analyseras (docx/xlsx i nästa steg).
- Ingen flytt av mail ännu, endast kategorier (mindre destruktivt).
- Token-cachen ligger okrypterad i volymen `appdata` — servern antas
  vara betrodd (din Proxmox bakom WireGuard).
