from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ISORegion(str, Enum):
    MISO = "MISO"
    PJM = "PJM"
    ERCOT = "ERCOT"


class Severity(str, Enum):
    BLOCKING = "blocking"
    WARNING = "warning"
    READY = "ready"


class Finding(BaseModel):
    id: str
    severity: Severity
    title: str
    detail: str
    rule_id: Optional[str] = None
    location: Optional[str] = None
    recommendation: Optional[str] = None
    evidence: Optional[str] = None


class EquipmentItem(BaseModel):
    type: str
    label: Optional[str] = None
    rating: Optional[str] = None
    notes: Optional[str] = None


class AuditExtract(BaseModel):
    project_name: Optional[str] = None
    capacity_mw: Optional[float] = None
    interconnection_voltage_kv: Optional[float] = None
    inverter_models: list[str] = Field(default_factory=list)
    transformers: list[str] = Field(default_factory=list)
    equipment: list[EquipmentItem] = Field(default_factory=list)
    observed_notes: list[str] = Field(default_factory=list)
    raw_summary: str = ""


class AuditReport(BaseModel):
    report_id: str
    project_name: str
    iso: ISORegion
    filename: str
    created_at: str
    readiness_score: int = Field(ge=0, le=100)
    status: Literal["not_ready", "needs_review", "ready"]
    summary: str
    findings: list[Finding]
    extract: AuditExtract
    rules_checked: list[str]
    pages_analyzed: int
    model: str
    mode: Literal["live", "demo"] = "live"


class AuditResponse(BaseModel):
    report: AuditReport
    html_url: str
    json_url: str


class HealthResponse(BaseModel):
    status: str
    model: str
    api_configured: bool


class ISOInfo(BaseModel):
    id: str
    name: str
    description: str
    rule_count: int


class DemoRequest(BaseModel):
    iso: ISORegion = ISORegion.PJM
    extras: dict[str, Any] = Field(default_factory=dict)
