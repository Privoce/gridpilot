from __future__ import annotations

import json
from typing import Any

from backend.app.db_models import AuditRun, Drawing, FindingRow, FindingTriage, Project


def drawing_out(d: Drawing) -> dict[str, Any]:
    return {
        "id": d.id,
        "filename": d.filename,
        "version_label": d.version_label,
        "page_count": d.page_count,
        "is_latest": d.is_latest,
        "created_at": d.created_at,
        "content_type": d.content_type,
    }


def audit_summary(a: AuditRun, drawing_filename: str | None = None) -> dict[str, Any]:
    return {
        "id": a.id,
        "status": a.status.value,
        "iso": a.iso,
        "project_id": a.project_id,
        "readiness_score": a.readiness_score,
        "readiness_status": a.readiness_status,
        "summary": a.summary,
        "model": a.model,
        "mode": a.mode,
        "blocking_open": a.blocking_open,
        "warning_open": a.warning_open,
        "pages_analyzed": a.pages_analyzed,
        "drawing_id": a.drawing_id,
        "drawing_filename": drawing_filename,
        "created_at": a.created_at,
        "completed_at": a.completed_at,
        "error": a.error,
    }


def finding_out(f: FindingRow) -> dict[str, Any]:
    return {
        "id": f.id,
        "severity": f.severity.value,
        "title": f.title,
        "detail": f.detail,
        "rule_id": f.rule_id,
        "location": f.location,
        "recommendation": f.recommendation,
        "evidence": f.evidence,
        "triage": f.triage.value,
        "triage_note": f.triage_note,
        "triaged_at": f.triaged_at,
    }


def filing_gate(findings: list[FindingRow]) -> dict[str, Any]:
    open_blocking = [
        f
        for f in findings
        if f.severity.value == "blocking" and f.triage == FindingTriage.OPEN
    ]
    open_warnings = [
        f
        for f in findings
        if f.severity.value == "warning"
        and f.triage in {FindingTriage.OPEN, FindingTriage.ACKNOWLEDGED}
    ]
    ready_checks = [f for f in findings if f.severity.value == "ready"]
    can_file = len(open_blocking) == 0
    return {
        "can_file": can_file,
        "gate": "ready_to_file" if can_file else "blocked",
        "open_blocking": len(open_blocking),
        "open_warnings": len(open_warnings),
        "ready_signals": len(ready_checks),
        "checklist": [
            {
                "id": f.id,
                "title": f.title,
                "severity": f.severity.value,
                "triage": f.triage.value,
                "recommendation": f.recommendation,
            }
            for f in findings
            if f.severity.value in {"blocking", "warning"}
        ],
    }


def project_out(
    p: Project,
    latest_drawing: Drawing | None = None,
    latest_audit: AuditRun | None = None,
) -> dict[str, Any]:
    open_blocking = latest_audit.blocking_open if latest_audit else 0
    open_warnings = latest_audit.warning_open if latest_audit else 0
    return {
        "id": p.id,
        "name": p.name,
        "iso": p.iso,
        "capacity_mw": p.capacity_mw,
        "state": p.state,
        "poi_substation": p.poi_substation,
        "status": p.status,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
        "latest_drawing": drawing_out(latest_drawing) if latest_drawing else None,
        "latest_audit": audit_summary(latest_audit, latest_drawing.filename if latest_drawing else None)
        if latest_audit
        else None,
        "open_blocking": open_blocking,
        "open_warnings": open_warnings,
    }


def audit_detail(a: AuditRun) -> dict[str, Any]:
    findings = sorted(
        a.findings,
        key=lambda f: (
            {"blocking": 0, "warning": 1, "ready": 2}.get(f.severity.value, 9),
            f.title,
        ),
    )
    extract = json.loads(a.extract_json) if a.extract_json else {}
    rules = json.loads(a.rules_checked_json) if a.rules_checked_json else []
    base = audit_summary(a, a.drawing.filename if a.drawing else None)
    base.update(
        {
            "extract": extract,
            "rules_checked": rules,
            "findings": [finding_out(f) for f in findings],
            "filing_gate": filing_gate(findings),
        }
    )
    return base
