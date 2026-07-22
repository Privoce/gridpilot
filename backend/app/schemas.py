from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=120)
    org_name: str = Field(min_length=1, max_length=160)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: EmailStr
    name: str


class OrgOut(BaseModel):
    id: str
    name: str
    slug: str
    plan: str
    audits_used_period: int
    audit_limit: int
    project_count: int
    project_limit: int
    role: str


class MeResponse(BaseModel):
    user: UserOut
    org: OrgOut
    is_demo: bool = False


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    iso: Literal["CAISO", "PJM", "MISO", "ERCOT", "SPP", "NYISO", "ISO-NE"] = "PJM"
    capacity_mw: Optional[float] = None
    state: Optional[str] = None
    poi_substation: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    iso: Optional[Literal["CAISO", "PJM", "MISO", "ERCOT", "SPP", "NYISO", "ISO-NE"]] = None
    capacity_mw: Optional[float] = None
    state: Optional[str] = None
    poi_substation: Optional[str] = None
    status: Optional[Literal["active", "archived"]] = None


class DrawingOut(BaseModel):
    id: str
    filename: str
    version_label: str
    page_count: int
    is_latest: bool
    created_at: datetime
    content_type: str


class ProjectOut(BaseModel):
    id: str
    name: str
    iso: str
    capacity_mw: Optional[float]
    state: Optional[str]
    poi_substation: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime
    latest_drawing: Optional[DrawingOut] = None
    latest_audit: Optional["AuditSummary"] = None
    open_blocking: int = 0
    open_warnings: int = 0


class FindingOut(BaseModel):
    id: str
    severity: str
    title: str
    detail: str
    rule_id: Optional[str]
    location: Optional[str]
    recommendation: Optional[str]
    evidence: Optional[str]
    triage: str
    triage_note: Optional[str]
    triaged_at: Optional[datetime]


class FindingTriageRequest(BaseModel):
    triage: Literal["open", "acknowledged", "resolved", "dismissed"]
    note: Optional[str] = None


class AuditSummary(BaseModel):
    id: str
    status: str
    iso: str
    project_id: str
    readiness_score: Optional[int]
    readiness_status: Optional[str]
    summary: Optional[str]
    model: Optional[str]
    mode: Optional[str]
    blocking_open: int
    warning_open: int
    pages_analyzed: int
    drawing_id: str
    drawing_filename: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime]
    error: Optional[str] = None


class AuditDetail(AuditSummary):
    extract: dict[str, Any] = Field(default_factory=dict)
    rules_checked: list[str] = Field(default_factory=list)
    findings: list[FindingOut] = Field(default_factory=list)
    filing_gate: dict[str, Any] = Field(default_factory=dict)


class DashboardOut(BaseModel):
    projects: int
    audits_this_period: int
    audit_limit: int
    open_blocking: int
    open_warnings: int
    recent_audits: list[AuditSummary]
    recent_projects: list[ProjectOut]


class BillingOut(BaseModel):
    plan: str
    audits_used_period: int
    audit_limit: int
    project_count: int
    project_limit: int
    period_start: datetime
    features: list[str]


ProjectOut.model_rebuild()
