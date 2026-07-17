from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class Plan(str, enum.Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class MemberRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    ENGINEER = "engineer"
    VIEWER = "viewer"


class AuditStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class FindingSeverity(str, enum.Enum):
    BLOCKING = "blocking"
    WARNING = "warning"
    READY = "ready"


class FindingTriage(str, enum.Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    memberships: Mapped[List["Membership"]] = relationship(back_populates="user")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uid)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    plan: Mapped[Plan] = mapped_column(Enum(Plan), default=Plan.FREE)
    audits_used_period: Mapped[int] = mapped_column(Integer, default=0)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    memberships: Mapped[List["Membership"]] = relationship(back_populates="org")
    projects: Mapped[List["Project"]] = relationship(back_populates="org")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "org_id", name="uq_member"),)

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    role: Mapped[MemberRole] = mapped_column(Enum(MemberRole), default=MemberRole.ENGINEER)

    user: Mapped["User"] = relationship(back_populates="memberships")
    org: Mapped["Organization"] = relationship(back_populates="memberships")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    iso: Mapped[str] = mapped_column(String(16), default="PJM")
    capacity_mw: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    poi_substation: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    org: Mapped["Organization"] = relationship(back_populates="projects")
    drawings: Mapped[List["Drawing"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    audits: Mapped[List["AuditRun"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Drawing(Base):
    __tablename__ = "drawings"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(80), default="application/pdf")
    version_label: Mapped[str] = mapped_column(String(64), default="Rev A")
    page_count: Mapped[int] = mapped_column(Integer, default=1)
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True)

    project: Mapped["Project"] = relationship(back_populates="drawings")
    audits: Mapped[List["AuditRun"]] = relationship(back_populates="drawing")


class AuditRun(Base):
    __tablename__ = "audit_runs"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    drawing_id: Mapped[str] = mapped_column(ForeignKey("drawings.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    iso: Mapped[str] = mapped_column(String(16))
    status: Mapped[AuditStatus] = mapped_column(Enum(AuditStatus), default=AuditStatus.QUEUED)
    readiness_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    readiness_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    mode: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extract_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rules_checked_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pages_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    blocking_open: Mapped[int] = mapped_column(Integer, default=0)
    warning_open: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="audits")
    drawing: Mapped["Drawing"] = relationship(back_populates="audits")
    findings: Mapped[List["FindingRow"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan"
    )


class FindingRow(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uid)
    audit_id: Mapped[str] = mapped_column(ForeignKey("audit_runs.id", ondelete="CASCADE"), index=True)
    external_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    severity: Mapped[FindingSeverity] = mapped_column(Enum(FindingSeverity))
    title: Mapped[str] = mapped_column(String(255))
    detail: Mapped[str] = mapped_column(Text, default="")
    rule_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    recommendation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    triage: Mapped[FindingTriage] = mapped_column(Enum(FindingTriage), default=FindingTriage.OPEN)
    triage_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    triaged_by: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    triaged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    audit: Mapped["AuditRun"] = relationship(back_populates="findings")
