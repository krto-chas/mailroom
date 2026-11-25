"""Datamodell: projects, emails, attachments, findings + delta-state.

Rå-mailen bor kvar i Outlook. Här lagras metadata, klassificering och
extraherade fynd — det som systemet resonerar kring.
"""
from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class KVState(Base):
    """Nyckel/värde för t.ex. Graph deltaLink."""
    __tablename__ = "kv_state"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)      # t.ex. "berghallen"
    name: Mapped[str] = mapped_column(String(200))                  # "Brf Berghällen, Vaxholm"
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)  # ["Norrberget etapp 2", ...]
    sender_domains: Mapped[list[str]] = mapped_column(JSON, default=list)  # ["besqab.se"]
    active: Mapped[bool] = mapped_column(default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    emails: Mapped[list[Email]] = relationship(back_populates="project")


class Category(str, enum.Enum):
    projektinfo = "projektinfo"
    motesprotokoll = "motesprotokoll"
    leverantorsfaktura = "leverantorsfaktura"
    kundfaktura = "kundfaktura"
    forfragan = "forfragan"
    admin = "admin"
    privat = "privat"
    brus = "brus"


class Email(Base):
    __tablename__ = "emails"
    __table_args__ = (UniqueConstraint("graph_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    graph_id: Mapped[str] = mapped_column(String(300))
    internet_message_id: Mapped[str | None] = mapped_column(String(500))
    conversation_id: Mapped[str | None] = mapped_column(String(300))
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    sender: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(Text, default="")
    body_preview: Mapped[str] = mapped_column(Text, default="")

    # Klassificering
    category: Mapped[Category | None] = mapped_column(Enum(Category), nullable=True)
    priority: Mapped[int | None] = mapped_column()  # 1=hög, 2=normal, 3=låg
    summary: Mapped[str] = mapped_column(Text, default="")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    project: Mapped[Project | None] = relationship(back_populates="emails")
    classified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    llm_raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # hela LLM-svaret, för felsökning

    # Mänsklig rättning (blir few-shot-underlag)
    corrected: Mapped[bool] = mapped_column(default=False)
    correction_note: Mapped[str] = mapped_column(Text, default="")

    # Åtgärd
    action_taken: Mapped[str] = mapped_column(String(64), default="none")  # none|shadow|categorized|moved
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    attachments: Mapped[list[Attachment]] = relationship(back_populates="email")
    findings: Mapped[list[Finding]] = relationship(back_populates="email")


class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    email_id: Mapped[int] = mapped_column(ForeignKey("emails.id"))
    email: Mapped[Email] = relationship(back_populates="attachments")
    name: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str | None] = mapped_column(String(200))
    size: Mapped[int] = mapped_column(default=0)
    sha256: Mapped[str | None] = mapped_column(String(64))
    analyzed: Mapped[bool] = mapped_column(default=False)
    extracted_chars: Mapped[int] = mapped_column(default=0)


class FindingStatus(str, enum.Enum):
    ny = "ny"
    sedd = "sedd"
    atgardad = "atgardad"
    avfard = "avfärdad"


class Finding(Base):
    """Flaggad punkt ur mail eller bilaga — t.ex. beslut i byggmötesprotokoll."""
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(primary_key=True)
    email_id: Mapped[int] = mapped_column(ForeignKey("emails.id"))
    email: Mapped[Email] = relationship(back_populates="findings")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(300))   # "brödtext" eller bilagans filnamn
    locator: Mapped[str] = mapped_column(String(120), default="")  # "sida 3, §7.2"
    text: Mapped[str] = mapped_column(Text)            # själva punkten
    why: Mapped[str] = mapped_column(Text, default="") # varför den flaggas för dig
    severity: Mapped[int] = mapped_column(default=2)   # 1=viktig, 2=notera, 3=info
    status: Mapped[FindingStatus] = mapped_column(Enum(FindingStatus), default=FindingStatus.ny)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
