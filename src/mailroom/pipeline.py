"""Pipelinen: hämta delta → klassificera → lagra → (ev.) agera → notifiera.

Shadow mode (default): allt loggas i databasen men inget mail rörs.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import logging

from sqlalchemy import select

from mailroom.classify.classifier import analyze_document, classify_email
from mailroom.config import settings
from mailroom.db.models import (
    Attachment,
    Category,
    Email,
    Finding,
    KVState,
    Project,
)
from mailroom.db.session import get_session
from mailroom.graph import client as graph
from mailroom.notify import notify

log = logging.getLogger("mailroom.pipeline")

DELTA_KEY = "graph_inbox_delta"

ANALYZABLE = {".pdf"}  # v0.1: PDF räcker; docx m.fl. i nästa steg


def _pdf_text(content: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:  # trasig/lösenordsskyddad PDF ska inte fälla pipelinen
        log.warning("PDF-extraktion misslyckades: %s", e)
        return ""


def run_once() -> None:
    with get_session() as db:
        state = db.get(KVState, DELTA_KEY)
        messages, new_delta = graph.fetch_delta(state.value if state else None)

        projects = [
            {
                "slug": p.slug,
                "name": p.name,
                "aliases": p.aliases,
                "sender_domains": p.sender_domains,
            }
            for p in db.scalars(select(Project).where(Project.active)).all()
        ]
        corrections = [
            {
                "sender": e.sender,
                "subject": e.subject,
                "project_slug": e.project.slug if e.project else None,
                "category": e.category.value if e.category else None,
                "note": e.correction_note,
            }
            for e in db.scalars(
                select(Email).where(Email.corrected).order_by(Email.id.desc()).limit(10)
            ).all()
        ]

        for msg in messages:
            if "@removed" in msg or "id" not in msg:
                continue
            if db.scalar(select(Email).where(Email.graph_id == msg["id"])):
                continue  # redan behandlat

            _process_message(db, msg, projects, corrections)

        if state:
            state.value = new_delta
        else:
            db.add(KVState(key=DELTA_KEY, value=new_delta))
        db.commit()


def _process_message(db, msg: dict, projects: list[dict], corrections: list[dict]) -> None:
    sender = (msg.get("from") or {}).get("emailAddress", {}).get("address", "okänd")
    subject = msg.get("subject") or ""
    body = (msg.get("body") or {}).get("content", "") or msg.get("bodyPreview", "")

    attachments = graph.fetch_attachments(msg["id"]) if msg.get("hasAttachments") else []
    att_names = [a["name"] for a in attachments]

    try:
        result = classify_email(
            sender=sender,
            subject=subject,
            body=body,
            attachment_names=att_names,
            projects=projects,
            corrections=corrections,
        )
    except Exception as e:
        log.error("Klassificering misslyckades för '%s': %s", subject, e)
        result = {}

    slug = result.get("project_slug")
    project = (
        db.scalar(select(Project).where(Project.slug == slug)) if slug else None
    )
    try:
        category = Category(result.get("category")) if result.get("category") else None
    except ValueError:
        category = None

    email = Email(
        graph_id=msg["id"],
        internet_message_id=msg.get("internetMessageId"),
        conversation_id=msg.get("conversationId"),
        received_at=dt.datetime.fromisoformat(msg["receivedDateTime"].replace("Z", "+00:00")),
        sender=sender,
        subject=subject,
        body_preview=msg.get("bodyPreview", ""),
        category=category,
        priority=result.get("priority"),
        summary=result.get("summary", ""),
        project=project,
        classified_at=dt.datetime.now(dt.timezone.utc),
        llm_raw=result or None,
        action_taken="shadow" if settings.shadow_mode else "none",
    )
    db.add(email)
    db.flush()

    # Flaggor ur brödtexten
    for f in result.get("flags", []):
        db.add(
            Finding(
                email_id=email.id,
                project_id=project.id if project else None,
                source="brödtext",
                text=str(f.get("text", "")),
                why=str(f.get("why", "")),
                severity=int(f.get("severity", 2)),
            )
        )

    # Bilagor: lagra metadata, djupanalysera protokoll/PDF
    for a in attachments:
        content = a.get("content")
        att = Attachment(
            email_id=email.id,
            name=a["name"],
            content_type=a.get("content_type"),
            size=a.get("size", 0),
            sha256=hashlib.sha256(content).hexdigest() if content else None,
        )
        db.add(att)
        suffix = "." + a["name"].rsplit(".", 1)[-1].lower() if "." in a["name"] else ""
        should_analyze = (
            content
            and suffix in ANALYZABLE
            and category in (Category.motesprotokoll, Category.projektinfo, Category.forfragan)
        )
        if should_analyze:
            text = _pdf_text(content)
            att.extracted_chars = len(text)
            if text.strip():
                try:
                    for f in analyze_document(filename=a["name"], text=text):
                        db.add(
                            Finding(
                                email_id=email.id,
                                project_id=project.id if project else None,
                                source=a["name"],
                                locator=str(f.get("locator", "")),
                                text=str(f.get("text", "")),
                                why=str(f.get("why", "")),
                                severity=int(f.get("severity", 2)),
                            )
                        )
                    att.analyzed = True
                except Exception as e:
                    log.error("Dokumentanalys misslyckades (%s): %s", a["name"], e)

    # Åtgärd mot Outlook — endast utanför shadow mode
    if not settings.shadow_mode and category:
        try:
            cats = [f"MR/{category.value}"]
            if project:
                cats.append(f"MR/{project.slug}")
            graph.set_categories(msg["id"], cats)
            email.action_taken = "categorized"
        except Exception as e:
            log.error("Kunde inte sätta kategorier: %s", e)

    # Notis vid viktiga fynd
    important = [f for f in email.findings if f.severity == 1]
    if important or (email.priority == 1):
        title = f"[{project.slug if project else '?'}] {subject[:80]}"
        lines = [email.summary] + [f"⚑ {f.text}" for f in important[:5]]
        notify(title=title, message="\n".join(x for x in lines if x))
