from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.db_models import AuditRun, FindingRow, FindingTriage
from backend.app.deps import AuthContext, get_auth
from backend.app.schemas import FindingTriageRequest
from backend.app.serializers import audit_detail, audit_summary, finding_out
from backend.app.services.durable import persist_audit, restore_audit, restore_audits_for_org
from backend.app.services.jobs import _recompute_open_counts
from backend.app.services.report import REPORT_TEMPLATE
from backend.app.seed import DEMO_ORG_ID

router = APIRouter(prefix="/api/audits", tags=["audits"])


def _get_audit(db: Session, auth: AuthContext, audit_id: str) -> AuditRun:
    audit = db.get(AuditRun, audit_id)
    if not audit and auth.org.id != DEMO_ORG_ID:
        # The audit may have completed on a different serverless instance.
        audit = restore_audit(db, auth.org.id, audit_id)
    if not audit or audit.org_id != auth.org.id:
        raise HTTPException(status_code=404, detail="Audit not found")
    return audit


@router.get("")
def list_audits(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    if auth.org.id != DEMO_ORG_ID:
        restore_audits_for_org(db, auth.org.id)
    audits = (
        db.query(AuditRun)
        .filter(AuditRun.org_id == auth.org.id)
        .order_by(AuditRun.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "audits": [
            audit_summary(a, a.drawing.filename if a.drawing else None) for a in audits
        ]
    }


@router.get("/{audit_id}")
def get_audit(
    audit_id: str,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    audit = _get_audit(db, auth, audit_id)
    return audit_detail(audit)


@router.get("/{audit_id}/report.html", response_class=HTMLResponse)
def audit_report_html(
    audit_id: str,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    audit = _get_audit(db, auth, audit_id)
    detail = audit_detail(audit)

    class _Obj:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    findings = []
    for f in detail["findings"]:
        findings.append(
            _Obj(
                severity=_Obj(value=f["severity"]),
                title=f["title"],
                detail=f["detail"],
                rule_id=f.get("rule_id"),
                location=f.get("location"),
                recommendation=f.get("recommendation"),
                evidence=f.get("evidence"),
            )
        )
    extract = detail.get("extract") or {}
    equipment = [
        _Obj(
            type=eq.get("type"),
            label=eq.get("label"),
            rating=eq.get("rating"),
            notes=eq.get("notes"),
        )
        for eq in extract.get("equipment") or []
    ]
    report = _Obj(
        report_id=audit.id,
        project_name=audit.project.name if audit.project else "Project",
        iso=_Obj(value=audit.iso),
        filename=audit.drawing.filename if audit.drawing else "",
        created_at=str(audit.created_at),
        readiness_score=audit.readiness_score or 0,
        status=audit.readiness_status or "needs_review",
        summary=audit.summary or "",
        findings=findings,
        extract=_Obj(equipment=equipment),
        rules_checked=detail.get("rules_checked") or [],
        pages_analyzed=audit.pages_analyzed,
        model=audit.model or "",
        mode=audit.mode or "live",
    )
    blocking = sum(1 for f in findings if f.severity.value == "blocking")
    warnings = sum(1 for f in findings if f.severity.value == "warning")
    ready = sum(1 for f in findings if f.severity.value == "ready")
    html = REPORT_TEMPLATE.render(
        report=report, blocking=blocking, warnings=warnings, ready=ready
    )
    return HTMLResponse(html)


@router.patch("/{audit_id}/findings/{finding_id}")
def triage_finding(
    audit_id: str,
    finding_id: str,
    payload: FindingTriageRequest,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    audit = _get_audit(db, auth, audit_id)
    finding = db.get(FindingRow, finding_id)
    if not finding or finding.audit_id != audit.id:
        raise HTTPException(status_code=404, detail="Finding not found")

    finding.triage = FindingTriage(payload.triage)
    finding.triage_note = payload.note
    finding.triaged_by = auth.user.id
    finding.triaged_at = datetime.now(timezone.utc)
    db.flush()
    _recompute_open_counts(db, audit)

    # Recompute readiness status from open blockers
    if audit.blocking_open > 0:
        audit.readiness_status = "not_ready"
    elif audit.warning_open > 0:
        audit.readiness_status = "needs_review"
    else:
        audit.readiness_status = "ready"

    db.commit()
    db.refresh(finding)
    db.refresh(audit)
    if auth.org.id != DEMO_ORG_ID:
        persist_audit(audit)
    return {
        "finding": finding_out(finding),
        "audit": audit_summary(audit, audit.drawing.filename if audit.drawing else None),
        "filing_gate": audit_detail(audit)["filing_gate"],
    }
