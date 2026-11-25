"""API + adminvy. Adminvyn (/) är en enkel sida för att granska
klassificeringar, rätta fel (few-shot-underlaget), beta av fynd och
registrera projekt — resultatet syns även i Outlook när shadow mode är av."""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from mailroom.config import settings
from mailroom.db.models import Category, Email, Finding, FindingStatus, Project
from mailroom.db.session import get_session, init_db

app = FastAPI(title="mailroom", version="0.2.0")

ADMIN_PAGE = Path(__file__).parent / "static" / "admin.html"


@app.on_event("startup")
def _startup() -> None:
    init_db()


def db_dep():
    db = get_session()
    try:
        yield db
    finally:
        db.close()


@app.get("/", include_in_schema=False)
def admin() -> FileResponse:
    return FileResponse(ADMIN_PAGE, media_type="text/html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "shadow_mode": settings.shadow_mode}


# --- Projekt ---

class ProjectIn(BaseModel):
    slug: str
    name: str
    aliases: list[str] = []
    sender_domains: list[str] = []
    notes: str = ""


@app.get("/projects")
def list_projects(db: Session = Depends(db_dep)) -> list[dict]:
    return [
        {"id": p.id, "slug": p.slug, "name": p.name, "aliases": p.aliases,
         "sender_domains": p.sender_domains, "active": p.active}
        for p in db.scalars(select(Project)).all()
    ]


@app.post("/projects")
def create_project(body: ProjectIn, db: Session = Depends(db_dep)) -> dict:
    if db.scalar(select(Project).where(Project.slug == body.slug)):
        raise HTTPException(409, "slug finns redan")
    p = Project(**body.model_dump())
    db.add(p)
    db.commit()
    return {"id": p.id, "slug": p.slug}


# --- Mail & rättningar ---

@app.get("/emails")
def list_emails(limit: int = 50, db: Session = Depends(db_dep)) -> list[dict]:
    limit = min(limit, 500)
    rows = db.scalars(select(Email).order_by(Email.id.desc()).limit(limit)).all()
    return [
        {"id": e.id, "received_at": e.received_at.isoformat(), "sender": e.sender,
         "subject": e.subject, "category": e.category.value if e.category else None,
         "priority": e.priority, "project": e.project.slug if e.project else None,
         "summary": e.summary, "corrected": e.corrected}
        for e in rows
    ]


class CorrectionIn(BaseModel):
    project_slug: str | None = None
    category: Category | None = None
    note: str = ""


@app.post("/emails/{email_id}/correct")
def correct_email(email_id: int, body: CorrectionIn, db: Session = Depends(db_dep)) -> dict:
    e = db.get(Email, email_id)
    if not e:
        raise HTTPException(404)
    if body.project_slug is not None:
        p = db.scalar(select(Project).where(Project.slug == body.project_slug))
        if not p:
            raise HTTPException(404, "okänt projekt")
        e.project = p
    if body.category is not None:
        e.category = body.category
    e.corrected = True
    e.correction_note = body.note
    db.commit()
    return {"ok": True}


# --- Fynd ---

@app.get("/findings")
def list_findings(status: FindingStatus | None = None, db: Session = Depends(db_dep)) -> list[dict]:
    q = select(Finding).order_by(Finding.severity, Finding.id.desc()).limit(200)
    if status:
        q = q.where(Finding.status == status)
    return [
        {"id": f.id, "email_id": f.email_id, "project_id": f.project_id,
         "source": f.source, "locator": f.locator, "text": f.text, "why": f.why,
         "severity": f.severity, "status": f.status.value}
        for f in db.scalars(q).all()
    ]


@app.post("/findings/{finding_id}/status")
def set_finding_status(finding_id: int, status: FindingStatus, db: Session = Depends(db_dep)) -> dict:
    f = db.get(Finding, finding_id)
    if not f:
        raise HTTPException(404)
    f.status = status
    db.commit()
    return {"ok": True}
