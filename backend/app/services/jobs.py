from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from backend.app.db import SessionLocal
from backend.app.db_models import (
    AuditRun,
    AuditStatus,
    FindingRow,
    FindingSeverity,
    FindingTriage,
)
from backend.app.models import ISORegion
from backend.app.services.audit import run_audit

logger = logging.getLogger("gridpilot.jobs")

_running: set[str] = set()


def _recompute_open_counts(db, audit: AuditRun) -> None:  # noqa: ANN001
    findings = (
        db.query(FindingRow).filter(FindingRow.audit_id == audit.id).all()
        if audit.id
        else list(audit.findings)
    )
    blocking = 0
    warning = 0
    for f in findings:
        if f.triage != FindingTriage.OPEN:
            continue
        sev = f.severity.value if hasattr(f.severity, "value") else str(f.severity)
        if sev == FindingSeverity.BLOCKING.value:
            blocking += 1
        elif sev == FindingSeverity.WARNING.value:
            warning += 1
    audit.blocking_open = blocking
    audit.warning_open = warning


async def execute_audit_run(audit_id: str) -> None:
    if audit_id in _running:
        return
    _running.add(audit_id)
    db = SessionLocal()
    try:
        audit = db.get(AuditRun, audit_id)
        if not audit:
            return

        drawing_path = Path(audit.drawing.stored_path)
        project_name = audit.project.name if audit.project else ""
        iso = audit.iso

        audit.status = AuditStatus.RUNNING
        audit.started_at = datetime.now(timezone.utc)
        audit.error = None
        db.commit()

        report, _, _ = await run_audit(
            file_path=drawing_path,
            iso=ISORegion(iso),
            project_name=project_name,
            force_demo=False,
        )

        audit = db.get(AuditRun, audit_id)
        assert audit
        for old in list(audit.findings):
            db.delete(old)
        db.flush()

        for f in report.findings:
            db.add(
                FindingRow(
                    audit_id=audit.id,
                    external_key=f.id,
                    severity=FindingSeverity(f.severity.value),
                    title=f.title,
                    detail=f.detail,
                    rule_id=f.rule_id,
                    location=f.location,
                    recommendation=f.recommendation,
                    evidence=f.evidence,
                    triage=FindingTriage.OPEN
                    if f.severity.value != "ready"
                    else FindingTriage.RESOLVED,
                )
            )
        db.flush()
        audit = db.get(AuditRun, audit_id)
        assert audit
        audit.status = AuditStatus.COMPLETED
        audit.readiness_score = report.readiness_score
        audit.readiness_status = report.status
        audit.summary = report.summary
        audit.model = report.model
        audit.mode = report.mode
        audit.pages_analyzed = report.pages_analyzed
        audit.extract_json = json.dumps(report.extract.model_dump())
        audit.rules_checked_json = json.dumps(report.rules_checked)
        audit.completed_at = datetime.now(timezone.utc)
        _recompute_open_counts(db, audit)
        db.commit()
        logger.info("Audit %s completed score=%s", audit_id, report.readiness_score)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Audit %s failed", audit_id)
        db.rollback()
        audit = db.get(AuditRun, audit_id)
        if audit:
            audit.status = AuditStatus.FAILED
            audit.error = str(exc)[:2000]
            audit.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()
        _running.discard(audit_id)


def enqueue_audit(audit_id: str) -> None:
    from backend.app.config import settings

    # On Vercel the function freezes after the response — run the audit inline.
    if settings.is_vercel:
        asyncio.run(execute_audit_run(audit_id))
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(execute_audit_run(audit_id))
    except RuntimeError:
        asyncio.run(execute_audit_run(audit_id))
